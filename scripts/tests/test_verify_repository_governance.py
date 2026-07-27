from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import verify_repository_governance as governance  # noqa: E402

RULESETS_PAGE = "rulesets?includes_parents=true&per_page=100&page=1"
ENVIRONMENTS_PAGE = "environments?per_page=100&page=1"
PRODUCTION_BRANCH_POLICIES_PAGE = (
    "environments/Production/deployment-branch-policies?per_page=100&page=1"
)


def desired_live_responses() -> dict[str, object]:
    return {
        RULESETS_PAGE: [{"id": 7}],
        "rulesets/7": {
            "id": 7,
            "node_id": "RRS_test",
            "name": "main",
            "source_type": "Repository",
            "source": "syshin0116/syshin0116.dev",
            "created_at": "2026-07-27T00:00:00Z",
            "updated_at": "2026-07-27T00:00:00Z",
            "target": "branch",
            "enforcement": "active",
            "bypass_actors": [],
            "conditions": {
                "ref_name": {
                    "include": ["~DEFAULT_BRANCH"],
                    "exclude": [],
                }
            },
            "rules": [
                {"type": "deletion"},
                {"type": "non_fast_forward"},
                {
                    "type": "pull_request",
                    "parameters": {
                        "required_approving_review_count": 0,
                        "require_code_owner_review": False,
                        "require_last_push_approval": False,
                    },
                },
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "strict_required_status_checks_policy": True,
                        "required_status_checks": [
                            {"context": "ci/check", "integration_id": 15368},
                            {
                                "context": "protocol/compat",
                                "integration_id": 15368,
                            },
                            {
                                "context": "wiki/verify",
                                "integration_id": 15368,
                            },
                        ],
                    },
                },
            ],
        },
        "actions/permissions": {
            "enabled": True,
            "allowed_actions": "all",
            "sha_pinning_required": True,
        },
        ENVIRONMENTS_PAGE: {
            "total_count": 2,
            "environments": [
                {"name": "Preview"},
                {"name": "Production"},
            ],
        },
        "environments/Preview": {
            "name": "Preview",
            "can_admins_bypass": True,
            "protection_rules": [],
            "deployment_branch_policy": None,
        },
        "environments/Production": {
            "name": "Production",
            "can_admins_bypass": True,
            "protection_rules": [
                {
                    "type": "required_reviewers",
                    "prevent_self_review": False,
                    "reviewers": [
                        {
                            "type": "User",
                            "reviewer": {"login": "syshin0116"},
                        }
                    ],
                },
                {"type": "branch_policy"},
            ],
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
        },
        PRODUCTION_BRANCH_POLICIES_PAGE: {
            "total_count": 1,
            "branch_policies": [{"name": "main", "type": "branch"}],
        },
    }


class LocalGovernanceTests(unittest.TestCase):
    def test_repository_policy_and_workflows_are_locally_valid(self) -> None:
        policy = governance.load_policy()
        self.assertEqual([], governance.validate_local(REPO_ROOT, policy))

    def test_unpinned_action_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflows = root / ".github/workflows"
            workflows.mkdir(parents=True)
            (workflows / "ci.yml").write_text(
                """
jobs:
  check:
    name: ci/check
    steps:
      - uses: actions/checkout@v7
  protocol:
    name: protocol/compat
  wiki:
    name: wiki/verify
""".lstrip(),
                encoding="utf-8",
            )
            for relative in (
                ".github/CODEOWNERS",
                ".github/dependabot.yml",
                ".github/pull_request_template.md",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("test\n", encoding="utf-8")
            policy = governance.load_policy()

            errors = governance.validate_local(root, policy)

        self.assertTrue(any("actions/checkout@v7" in error for error in errors))

    def test_container_digest_is_not_mistaken_for_an_action_commit(self) -> None:
        reference = "docker://example/image@" + "a" * 40

        self.assertIsNone(governance.FULL_SHA_ACTION.fullmatch(reference))

    def test_flow_mapping_uses_is_found_by_ast_walk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "flow.yml"
            workflow.write_text(
                'jobs: {check: {steps: [{"uses": actions/checkout@v7}]}}\n',
                encoding="utf-8",
            )

            document = governance.load_yaml_document(workflow)
            references = list(governance.external_action_references(document))

        self.assertEqual([(1, "actions/checkout@v7")], references)

    def test_explicit_quoted_uses_key_is_found_by_ast_walk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "explicit.yml"
            workflow.write_text(
                """
jobs:
  check:
    steps:
      - ? "uses"
        : actions/checkout@v7
""".lstrip(),
                encoding="utf-8",
            )

            document = governance.load_yaml_document(workflow)
            references = list(governance.external_action_references(document))

        self.assertEqual([(5, "actions/checkout@v7")], references)

    def test_duplicate_yaml_key_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "duplicate.yml"
            workflow.write_text(
                """
jobs:
  check:
    name: first
    name: second
""".lstrip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                governance.GovernanceError,
                "duplicate YAML key 'name'",
            ):
                governance.load_yaml_document(workflow)

    def test_yaml_anchor_and_alias_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "alias.yml"
            workflow.write_text(
                """
shared: &shared
  uses: actions/checkout@v7
jobs:
  check:
    steps:
      - *shared
""".lstrip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                governance.GovernanceError,
                "anchors, aliases",
            ):
                governance.load_yaml_document(workflow)

    def test_yaml_merge_key_fails_closed_without_an_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "merge.yml"
            workflow.write_text(
                "jobs: {check: {<<: {name: ci/check}}}\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                governance.GovernanceError,
                "YAML merge key",
            ):
                governance.load_yaml_document(workflow)

    def test_local_action_reference_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "local.yml"
            workflow.write_text(
                "jobs: {check: {uses: ./.github/workflows/check.yml}}\n",
                encoding="utf-8",
            )

            document = governance.load_yaml_document(workflow)

        self.assertEqual(
            [],
            list(governance.external_action_references(document)),
        )

    def test_nested_workflow_is_included_in_repository_ast_walk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / ".github/workflows/nested/check.yaml"
            nested.parent.mkdir(parents=True)
            nested.write_text(
                "jobs: {check: {uses: actions/checkout@v7}}\n",
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(
            any(
                ".github/workflows/nested/check.yaml" in error
                and "actions/checkout@v7" in error
                for error in errors
            )
        )

    def test_nested_local_composite_action_is_walked_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/check.yml"
            outer = root / ".github/actions/outer/action.yml"
            inner = root / ".github/actions/inner/action.yaml"
            workflow.parent.mkdir(parents=True)
            outer.parent.mkdir(parents=True)
            inner.parent.mkdir(parents=True)
            workflow.write_text(
                "jobs: {check: {uses: ./.github/actions/outer}}\n",
                encoding="utf-8",
            )
            outer.write_text(
                """
name: outer
runs:
  using: composite
  steps:
    - uses: ./.github/actions/inner
""".lstrip(),
                encoding="utf-8",
            )
            inner.write_text(
                """
name: inner
runs:
  using: composite
  steps:
    - uses: actions/checkout@v7
""".lstrip(),
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(
            any(
                ".github/actions/inner/action.yaml" in error
                and "actions/checkout@v7" in error
                for error in errors
            )
        )

    def test_local_action_target_escape_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/check.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "jobs: {check: {uses: ./../outside}}\n",
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(any("escapes the repository" in error for error in errors))

    def test_missing_local_action_target_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/check.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "jobs: {check: {uses: ./.github/actions/missing}}\n",
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(any("missing or unsupported" in error for error in errors))

    def test_local_action_cycle_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / ".github/actions/first/action.yml"
            second = root / ".github/actions/second/action.yml"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_text(
                """
name: first
runs:
  using: composite
  steps:
    - uses: ./.github/actions/second
""".lstrip(),
                encoding="utf-8",
            )
            second.write_text(
                """
name: second
runs:
  using: composite
  steps:
    - uses: ./.github/actions/first
""".lstrip(),
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(any("local uses cycle detected" in error for error in errors))

    def test_dependency_audit_events_are_schedule_and_manual_only(self) -> None:
        workflow = REPO_ROOT / ".github/workflows/dependency-audit.yml"
        document = governance.load_yaml_document(workflow)

        self.assertEqual(
            {"schedule", "workflow_dispatch"},
            governance.workflow_events(document),
        )
        self.assertFalse(
            any(
                governance._nodes_for_mapping_key(
                    document.root,
                    "continue-on-error",
                )
            )
        )

    def test_dependabot_groups_match_the_exact_policy(self) -> None:
        policy = governance.load_policy()

        self.assertEqual(
            [],
            governance.validate_dependabot_grouping(
                REPO_ROOT / ".github/dependabot.yml",
                policy,
            ),
        )

    def test_dependabot_compatibility_surface_exclusions_are_exact(self) -> None:
        document = governance.load_yaml_document(REPO_ROOT / ".github/dependabot.yml")
        groups = governance._normalized_dependabot_groups(document)

        self.assertEqual(
            sorted(
                [
                    "@assistant-ui/*",
                    "@auth/*",
                    "@langchain/*",
                    "next",
                    "next-auth",
                ]
            ),
            groups["npm:/web:web-routine"]["exclude_patterns"],
        )
        self.assertEqual(
            sorted(
                [
                    "aegra-*",
                    "deepagents",
                    "langchain",
                    "langchain-*",
                    "langgraph",
                    "langgraph-*",
                    "langsmith",
                ]
            ),
            groups["pip:/agent:agent-routine"]["exclude_patterns"],
        )

    def test_dependabot_group_pattern_mutation_is_rejected(self) -> None:
        policy = governance.load_policy()
        original = (REPO_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            mutated = Path(directory) / "dependabot.yml"
            mutated.write_text(
                original.replace('          - "@auth/*"\n', ""),
                encoding="utf-8",
            )

            errors = governance.validate_dependabot_grouping(mutated, policy)

        self.assertTrue(
            any("@auth/*" in error and "web-routine" in error for error in errors)
        )

    def test_duplicate_required_check_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflows = root / ".github/workflows"
            workflows.mkdir(parents=True)
            (workflows / "one.yml").write_text(
                "jobs:\n  first:\n    name: ci/check\n",
                encoding="utf-8",
            )
            (workflows / "two.yml").write_text(
                "jobs:\n  second:\n    name: ci/check\n",
                encoding="utf-8",
            )
            policy = {
                "main": {
                    "required_checks": [
                        {"context": "ci/check", "integration_id": 15368},
                        {
                            "context": "protocol/compat",
                            "integration_id": 15368,
                        },
                        {"context": "wiki/verify", "integration_id": 15368},
                    ]
                }
            }

            errors = governance.validate_local(root, policy)

        self.assertIn(
            "local: required check 'ci/check' must be emitted by exactly "
            "one job, found 2",
            errors,
        )


class LiveGovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = governance.load_policy()

    def test_desired_external_state_passes(self) -> None:
        responses = desired_live_responses()

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertEqual([], errors)

    def test_solo_deadlocks_and_missing_guards_are_reported(self) -> None:
        responses = desired_live_responses()
        ruleset = json.loads(json.dumps(responses["rulesets/7"]))
        ruleset["rules"] = [
            rule for rule in ruleset["rules"] if rule["type"] != "non_fast_forward"
        ]
        pull_request = next(
            rule for rule in ruleset["rules"] if rule["type"] == "pull_request"
        )
        pull_request["parameters"]["required_approving_review_count"] = 1
        pull_request["parameters"]["require_code_owner_review"] = True
        responses["rulesets/7"] = ruleset
        responses["actions/permissions"] = {
            "enabled": True,
            "sha_pinning_required": False,
        }

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertTrue(any("non_fast_forward" in error for error in errors))
        self.assertTrue(any("requires 1 approvals" in error for error in errors))
        self.assertTrue(
            any(
                "Code Owner review must be explicitly disabled" in error
                for error in errors
            )
        )
        self.assertTrue(any("full-SHA policy is False" in error for error in errors))

    def test_disabled_actions_are_reported(self) -> None:
        responses = desired_live_responses()
        responses["actions/permissions"] = {
            "enabled": False,
            "allowed_actions": "all",
            "sha_pinning_required": True,
        }

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertIn(
            "external: GitHub Actions enabled policy is False; expected True",
            errors,
        )

    def test_required_check_bindings_compare_wrong_and_duplicates_exactly(self) -> None:
        responses = desired_live_responses()
        ruleset = json.loads(json.dumps(responses["rulesets/7"]))
        status = next(
            rule
            for rule in ruleset["rules"]
            if rule["type"] == "required_status_checks"
        )
        status["parameters"]["required_status_checks"] = [
            {"context": "ci/check", "integration_id": 15368},
            {"context": "ci/check", "integration_id": 15368},
            {"context": "protocol/compat", "integration_id": 999},
            {"context": "unexpected/check", "integration_id": 15368},
        ]
        responses["rulesets/7"] = ruleset

        errors = governance.verify_live(self.policy, responses.__getitem__)

        mismatch = next(
            error
            for error in errors
            if "required check bindings differ exactly" in error
        )
        self.assertIn("wiki/verify", mismatch)
        self.assertIn("unexpected/check", mismatch)
        self.assertIn("999", mismatch)
        self.assertIn("duplicates=[('ci/check', 15368)]", mismatch)

    def test_required_check_missing_integration_id_fails_closed(self) -> None:
        responses = desired_live_responses()
        ruleset = json.loads(json.dumps(responses["rulesets/7"]))
        status = next(
            rule
            for rule in ruleset["rules"]
            if rule["type"] == "required_status_checks"
        )
        del status["parameters"]["required_status_checks"][0]["integration_id"]
        responses["rulesets/7"] = ruleset

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertTrue(
            any(
                "without a valid context/integration_id binding" in error
                for error in errors
            )
        )

    def test_extra_and_duplicate_ruleset_types_fail_closed(self) -> None:
        responses = desired_live_responses()
        ruleset = json.loads(json.dumps(responses["rulesets/7"]))
        ruleset["rules"].append({"type": "deletion"})
        ruleset["rules"].append(
            {
                "type": "required_deployments",
                "parameters": {"required_deployment_environments": ["Production"]},
            }
        )
        responses["rulesets/7"] = ruleset

        errors = governance.verify_live(self.policy, responses.__getitem__)

        mismatch = next(
            error for error in errors if "rule types differ exactly" in error
        )
        self.assertIn("required_deployments", mismatch)
        self.assertIn("duplicates=['deletion']", mismatch)

    def test_every_main_ruleset_bypass_actor_is_rejected(self) -> None:
        responses = desired_live_responses()
        ruleset = json.loads(json.dumps(responses["rulesets/7"]))
        ruleset["bypass_actors"] = [
            {"actor_type": "RepositoryRole", "actor_id": 5, "bypass_mode": "always"},
            {"actor_type": "Team", "actor_id": 17, "bypass_mode": "pull_request"},
        ]
        responses["rulesets/7"] = ruleset

        errors = governance.verify_live(self.policy, responses.__getitem__)

        bypass_error = next(error for error in errors if "bypass actors" in error)
        self.assertIn("RepositoryRole", bypass_error)
        self.assertIn("Team", bypass_error)

    def test_disabled_main_ruleset_is_not_silently_ignored(self) -> None:
        responses = desired_live_responses()
        ruleset = json.loads(json.dumps(responses["rulesets/7"]))
        ruleset["enforcement"] = "disabled"
        responses["rulesets/7"] = ruleset

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertTrue(any("inactive branch rulesets" in error for error in errors))
        self.assertTrue(any("0 active branch rulesets" in error for error in errors))

    def test_rules_split_across_active_rulesets_are_rejected(self) -> None:
        responses = desired_live_responses()
        first = json.loads(json.dumps(responses["rulesets/7"]))
        second = json.loads(json.dumps(responses["rulesets/7"]))
        first["rules"] = first["rules"][:2]
        second["id"] = 8
        second["name"] = "main-part-two"
        second["rules"] = second["rules"][2:]
        responses[RULESETS_PAGE] = [{"id": 7}, {"id": 8}]
        responses["rulesets/7"] = first
        responses["rulesets/8"] = second

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertTrue(
            any(
                "2 active branch rulesets" in error and "distributed" in error
                for error in errors
            )
        )

    def test_preview_mandatory_reviewer_is_rejected(self) -> None:
        responses = desired_live_responses()
        preview = json.loads(json.dumps(responses["environments/Preview"]))
        preview["protection_rules"] = [
            {
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [
                    {
                        "type": "User",
                        "reviewer": {"login": "syshin0116"},
                    }
                ],
            }
        ]
        responses["environments/Preview"] = preview

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertTrue(
            any("environment 'Preview' protection rules" in error for error in errors)
        )

    def test_production_self_review_deadlock_is_rejected(self) -> None:
        responses = desired_live_responses()
        production = json.loads(json.dumps(responses["environments/Production"]))
        required_reviewers = production["protection_rules"][0]
        required_reviewers["prevent_self_review"] = True
        responses["environments/Production"] = production

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertTrue(
            any(
                "environment 'Production' protection rules" in error
                and "prevent_self_review" in error
                for error in errors
            )
        )

    def test_production_reviewer_identity_drift_is_rejected(self) -> None:
        responses = desired_live_responses()
        production = json.loads(json.dumps(responses["environments/Production"]))
        required_reviewers = production["protection_rules"][0]
        required_reviewers["reviewers"][0]["reviewer"]["login"] = "another-owner"
        responses["environments/Production"] = production

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertTrue(
            any(
                "environment 'Production' protection rules" in error
                and "another-owner" in error
                for error in errors
            )
        )

    def test_extra_environment_is_rejected_as_policy_drift(self) -> None:
        responses = desired_live_responses()
        environments = json.loads(json.dumps(responses[ENVIRONMENTS_PAGE]))
        environments["total_count"] = 3
        environments["environments"].append({"name": "Staging"})
        responses[ENVIRONMENTS_PAGE] = environments

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertTrue(
            any(
                "GitHub environments differ exactly" in error and "Staging" in error
                for error in errors
            )
        )

    def test_ruleset_pagination_link_fails_closed(self) -> None:
        responses = desired_live_responses()
        responses[RULESETS_PAGE] = governance.ApiResponse(
            payload=responses[RULESETS_PAGE],
            headers={"link": '<https://api.github.test/rulesets?page=2>; rel="next"'},
        )

        with self.assertRaisesRegex(
            governance.GovernanceError,
            "requires pagination",
        ):
            governance.verify_live(self.policy, responses.__getitem__)

    def test_environment_total_count_mismatch_fails_closed(self) -> None:
        responses = desired_live_responses()
        environments = json.loads(json.dumps(responses[ENVIRONMENTS_PAGE]))
        environments["total_count"] = 3
        responses[ENVIRONMENTS_PAGE] = environments

        with self.assertRaisesRegex(
            governance.GovernanceError,
            "total_count is 3",
        ):
            governance.verify_live(self.policy, responses.__getitem__)

    def test_branch_policy_pagination_link_fails_closed(self) -> None:
        responses = desired_live_responses()
        responses[PRODUCTION_BRANCH_POLICIES_PAGE] = governance.ApiResponse(
            payload=responses[PRODUCTION_BRANCH_POLICIES_PAGE],
            headers={
                "link": ('<https://api.github.test/branch-policies?page=2>; rel="next"')
            },
        )

        with self.assertRaisesRegex(
            governance.GovernanceError,
            "requires pagination",
        ):
            governance.verify_live(self.policy, responses.__getitem__)


if __name__ == "__main__":
    unittest.main()
