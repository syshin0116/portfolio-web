from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import verify_repository_governance as governance  # noqa: E402


def desired_live_responses() -> dict[str, object]:
    return {
        "rulesets?includes_parents=true": [{"id": 7}],
        "rulesets/7": {
            "id": 7,
            "target": "branch",
            "enforcement": "active",
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
                            {"context": "ci/check"},
                            {"context": "protocol/compat"},
                            {"context": "wiki/verify"},
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
        "environments?per_page=100": {
            "total_count": 2,
            "environments": [
                {"name": "Preview"},
                {"name": "Production"},
            ],
        },
        "environments/Preview": {
            "name": "Preview",
            "deployment_branch_policy": None,
        },
        "environments/Production": {
            "name": "Production",
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
        },
        "environments/Production/deployment-branch-policies?per_page=100": {
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
                        "ci/check",
                        "protocol/compat",
                        "wiki/verify",
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
            any("Code Owner approval is required" in error for error in errors)
        )
        self.assertTrue(any("full-SHA policy is False" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
