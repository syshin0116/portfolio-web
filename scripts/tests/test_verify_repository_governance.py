from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import verify_repository_governance as governance  # noqa: E402

RULESETS_PAGE = "rulesets?includes_parents=true&per_page=100&page=1"
ENVIRONMENTS_PAGE = "environments?per_page=100&page=1"
PRODUCTION_BRANCH_POLICIES_PAGE = (
    "environments/Production/deployment-branch-policies?per_page=100&page=1"
)
EVAL_PUBLICATION_BRANCH_POLICIES_PAGE = (
    "environments/Evaluation%20Publication/"
    "deployment-branch-policies?per_page=100&page=1"
)
EVAL_PUBLICATION_SECRETS_PAGE = (
    "environments/Evaluation%20Publication/secrets?per_page=100&page=1"
)
EVAL_PUBLICATION_VARIABLES_PAGE = (
    "environments/Evaluation%20Publication/variables?per_page=100&page=1"
)
AGENT_PRODUCTION_BRANCH_POLICIES_PAGE = (
    "environments/Agent%20Production/deployment-branch-policies?per_page=100&page=1"
)
AGENT_PREVIEW_SECRETS_PAGE = "environments/Agent%20Preview/secrets?per_page=100&page=1"
AGENT_PREVIEW_VARIABLES_PAGE = (
    "environments/Agent%20Preview/variables?per_page=100&page=1"
)
AGENT_PRODUCTION_SECRETS_PAGE = (
    "environments/Agent%20Production/secrets?per_page=100&page=1"
)
AGENT_PRODUCTION_VARIABLES_PAGE = (
    "environments/Agent%20Production/variables?per_page=100&page=1"
)
LEGACY_MAIN_PROTECTION = "branches/main/protection"


def desired_live_responses() -> dict[str, object]:
    return {
        "": {
            "full_name": "syshin0116/syshin0116.dev",
            "default_branch": "main",
            "allow_merge_commit": True,
            "allow_squash_merge": True,
            "allow_rebase_merge": True,
            "security_and_analysis": {
                "dependabot_security_updates": {"status": "enabled"}
            },
        },
        "vulnerability-alerts": governance.ApiResponse(
            payload=None,
            headers={},
            status=204,
        ),
        "automated-security-fixes": {
            "enabled": True,
            "paused": False,
        },
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
                        "allowed_merge_methods": [
                            "merge",
                            "squash",
                            "rebase",
                        ],
                        "dismiss_stale_reviews_on_push": False,
                        "required_approving_review_count": 0,
                        "require_code_owner_review": False,
                        "require_last_push_approval": False,
                        "required_review_thread_resolution": False,
                        "required_reviewers": [],
                    },
                },
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "do_not_enforce_on_create": False,
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
        LEGACY_MAIN_PROTECTION: governance.ApiResponse(
            payload={"message": "Branch not protected", "status": "404"},
            headers={},
            status=404,
        ),
        ENVIRONMENTS_PAGE: {
            "total_count": 5,
            "environments": [
                {"name": "Evaluation Publication"},
                {"name": "Agent Preview"},
                {"name": "Agent Production"},
                {"name": "Preview"},
                {"name": "Production"},
            ],
        },
        "environments/Evaluation%20Publication": {
            "name": "Evaluation Publication",
            "can_admins_bypass": False,
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
        "environments/Agent%20Preview": {
            "name": "Agent Preview",
            "can_admins_bypass": False,
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
                }
            ],
            "deployment_branch_policy": None,
        },
        "environments/Agent%20Production": {
            "name": "Agent Production",
            "can_admins_bypass": False,
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
        EVAL_PUBLICATION_BRANCH_POLICIES_PAGE: {
            "total_count": 1,
            "branch_policies": [{"name": "main", "type": "branch"}],
        },
        EVAL_PUBLICATION_SECRETS_PAGE: {
            "total_count": 0,
            "secrets": [],
        },
        EVAL_PUBLICATION_VARIABLES_PAGE: {
            "total_count": 0,
            "variables": [],
        },
        AGENT_PREVIEW_SECRETS_PAGE: {
            "total_count": 1,
            "secrets": [{"name": "AGENT_SMOKE_BEARER_TOKEN"}],
        },
        AGENT_PREVIEW_VARIABLES_PAGE: {
            "total_count": 0,
            "variables": [],
        },
        AGENT_PRODUCTION_SECRETS_PAGE: {
            "total_count": 1,
            "secrets": [{"name": "AGENT_SMOKE_BEARER_TOKEN"}],
        },
        AGENT_PRODUCTION_VARIABLES_PAGE: {
            "total_count": 0,
            "variables": [],
        },
        AGENT_PRODUCTION_BRANCH_POLICIES_PAGE: {
            "total_count": 1,
            "branch_policies": [{"name": "main", "type": "branch"}],
        },
    }


def copy_local_governance_fixture(directory: str) -> Path:
    root = Path(directory)
    shutil.copytree(REPO_ROOT / ".github", root / ".github")
    shutil.copy2(REPO_ROOT / ".dockerignore", root / ".dockerignore")
    shutil.copy2(REPO_ROOT / "Dockerfile", root / "Dockerfile")
    shutil.copy2(REPO_ROOT / "pyproject.toml", root / "pyproject.toml")
    dockerfile = root / governance.PUBLICATION_DOCKERFILE
    dockerfile.parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / governance.PUBLICATION_DOCKERFILE, dockerfile)
    publication_ignore = root / governance.PUBLICATION_DOCKERIGNORE
    shutil.copy2(
        REPO_ROOT / governance.PUBLICATION_DOCKERIGNORE,
        publication_ignore,
    )
    identity_validator = root / governance.AGENT_DELIVERY_IDENTITY_SCRIPT
    identity_validator.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        REPO_ROOT / governance.AGENT_DELIVERY_IDENTITY_SCRIPT,
        identity_validator,
    )
    candidate_validator = root / governance.AGENT_RELEASE_CANDIDATE_SCRIPT
    candidate_validator.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        REPO_ROOT / governance.AGENT_RELEASE_CANDIDATE_SCRIPT,
        candidate_validator,
    )
    vercel_config = root / governance.VERCEL_CONFIG
    vercel_config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / governance.VERCEL_CONFIG, vercel_config)
    upstream_audit = root / governance.UPSTREAM_VERSION_AUDIT_SCRIPT
    upstream_audit.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        REPO_ROOT / governance.UPSTREAM_VERSION_AUDIT_SCRIPT,
        upstream_audit,
    )
    for relative in governance.VERCEL_PRODUCTION_OBSERVER_FILES_SHA256:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    return root


class LocalGovernanceTests(unittest.TestCase):
    def test_repository_policy_and_workflows_are_locally_valid(self) -> None:
        policy = governance.load_policy()
        self.assertEqual([], governance.validate_local(REPO_ROOT, policy))

    def test_vercel_git_autodeploy_contract_rejects_disabled_main_override(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            vercel_config = root / governance.VERCEL_CONFIG
            config = json.loads(vercel_config.read_text(encoding="utf-8"))
            config["git"] = {"deploymentEnabled": {"main": False}}
            vercel_config.write_text(
                json.dumps(config, indent=2) + "\n",
                encoding="utf-8",
            )

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any("Vercel Git auto-deploy contract differs" in error for error in errors),
            errors,
        )

    def test_vercel_git_autodeploy_contract_rejects_redundant_main_override(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            vercel_config = root / governance.VERCEL_CONFIG
            config = json.loads(vercel_config.read_text(encoding="utf-8"))
            config["git"] = {"deploymentEnabled": {"main": True}}
            vercel_config.write_text(
                json.dumps(config, indent=2) + "\n",
                encoding="utf-8",
            )

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any("Vercel Git auto-deploy contract differs" in error for error in errors),
            errors,
        )

    def test_vercel_git_autodeploy_contract_rejects_empty_git_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            vercel_config = root / governance.VERCEL_CONFIG
            config = json.loads(vercel_config.read_text(encoding="utf-8"))
            config["git"] = {}
            vercel_config.write_text(
                json.dumps(config, indent=2) + "\n",
                encoding="utf-8",
            )

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any("Vercel Git auto-deploy contract differs" in error for error in errors),
            errors,
        )

    def test_vercel_git_autodeploy_contract_rejects_unofficial_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            vercel_config = root / governance.VERCEL_CONFIG
            config = json.loads(vercel_config.read_text(encoding="utf-8"))
            config["$schema"] = "https://example.invalid/vercel.json"
            vercel_config.write_text(
                json.dumps(config, indent=2) + "\n",
                encoding="utf-8",
            )

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any("Vercel Git auto-deploy contract differs" in error for error in errors),
            errors,
        )

    def test_vercel_git_autodeploy_contract_rejects_preview_branch_override(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            vercel_config = root / governance.VERCEL_CONFIG
            config = json.loads(vercel_config.read_text(encoding="utf-8"))
            config["git"] = {"deploymentEnabled": {"preview/example": False}}
            vercel_config.write_text(
                json.dumps(config, indent=2) + "\n",
                encoding="utf-8",
            )

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any("Vercel Git auto-deploy contract differs" in error for error in errors),
            errors,
        )

    def test_vercel_git_autodeploy_contract_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            vercel_config = root / governance.VERCEL_CONFIG
            original = vercel_config.read_text(encoding="utf-8")
            mutated = original.replace(
                '"$schema": "https://openapi.vercel.sh/vercel.json"',
                '"$schema": "https://example.invalid/vercel.json",\n'
                '  "$schema": "https://openapi.vercel.sh/vercel.json"',
                1,
            )
            self.assertNotEqual(original, mutated)
            vercel_config.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any("cannot be read as strict JSON" in error for error in errors),
            errors,
        )

    def test_vercel_production_observer_rejects_workflow_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            workflow = root / governance.VERCEL_PRODUCTION_WORKFLOW
            original = workflow.read_text(encoding="utf-8")
            mutated = original.replace(
                "contents: read",
                "contents: write",
                1,
            )
            self.assertNotEqual(original, mutated)
            workflow.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any("exact workflow AST differs" in error for error in errors),
            errors,
        )

    def test_vercel_production_observer_requires_the_event_deployment_url(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            workflow = root / governance.VERCEL_PRODUCTION_WORKFLOW
            original = workflow.read_text(encoding="utf-8")
            mutated = original.replace(
                '            test -n "$EXPECTED_DEPLOYMENT_URL"\n',
                "",
                1,
            )
            self.assertNotEqual(original, mutated)
            workflow.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any("exact workflow AST differs" in error for error in errors),
            errors,
        )

    def test_vercel_production_observer_rejects_runtime_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            observer = root / "web/lib/vercel-production-revision.ts"
            observer.write_text(
                observer.read_text(encoding="utf-8").replace(
                    '"production"',
                    '"preview"',
                    1,
                ),
                encoding="utf-8",
            )

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(
                "exact reviewed credential-free Vercel production observer" in error
                for error in errors
            ),
            errors,
        )

    def test_publication_docker_context_scope_and_copy_inputs_are_exact(self) -> None:
        rules = governance.publication_dockerignore_rules(REPO_ROOT)
        sources = governance.publication_docker_copy_sources(REPO_ROOT)
        self.assertEqual(
            governance.EXPECTED_PUBLICATION_DOCKER_SCOPE_RULES,
            rules[: len(governance.EXPECTED_PUBLICATION_DOCKER_SCOPE_RULES)],
        )
        self.assertEqual(
            governance.EXPECTED_PUBLICATION_DOCKER_COPY_SOURCES,
            sources,
        )

    def test_root_docker_context_has_no_exceptions_and_all_required_denies(
        self,
    ) -> None:
        rules = governance.root_dockerignore_rules(REPO_ROOT)
        self.assertFalse(any(rule.startswith("!") for rule in rules))
        required = (
            *governance.REQUIRED_ROOT_DOCKER_ARTIFACT_DENY_RULES,
            *governance.REQUIRED_PUBLICATION_DOCKER_DENY_RULES,
        )
        self.assertTrue(set(required).issubset(rules))

    def test_publication_docker_context_rejects_deleted_sensitive_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            dockerignore = root / governance.PUBLICATION_DOCKERIGNORE
            original = dockerignore.read_text(encoding="utf-8")
            mutated = original.replace("**/*.pem\n", "", 1)
            self.assertNotEqual(original, mutated)
            dockerignore.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(
                "required terminal deny rule is missing: '**/*.pem'" in error
                for error in errors
            ),
            errors,
        )

    def test_publication_docker_context_rejects_deleted_parent_reclosure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            dockerignore = root / governance.PUBLICATION_DOCKERIGNORE
            original = dockerignore.read_text(encoding="utf-8")
            mutated = original.replace("agent/**\n", "", 1)
            self.assertNotEqual(original, mutated)
            dockerignore.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any("scope rules differ" in error for error in errors),
            errors,
        )

    def test_root_docker_context_rejects_deleted_environment_rule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            dockerignore = root / ".dockerignore"
            original = dockerignore.read_text(encoding="utf-8")
            mutated = original.replace("**/.env\n", "", 1)
            self.assertNotEqual(original, mutated)
            dockerignore.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(
                ".dockerignore required deny rule is missing: '**/.env'" in error
                for error in errors
            ),
            errors,
        )

    def test_agent_delivery_permission_chain_rejects_oidc_downgrade(self) -> None:
        cases = tuple(governance.AGENT_DELIVERY_WORKFLOW_AST_SHA256)
        for relative in cases:
            with (
                self.subTest(workflow=relative),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = copy_local_governance_fixture(directory)
                workflow = root / relative
                original = workflow.read_text(encoding="utf-8")
                mutated = original.replace("id-token: write", "id-token: none", 1)
                self.assertNotEqual(original, mutated)
                workflow.write_text(mutated, encoding="utf-8")

                errors = governance.validate_local(root, governance.load_policy())

            self.assertTrue(
                any(
                    relative in error and "exact workflow AST differs" in error
                    for error in errors
                ),
                errors,
            )

    def test_reusable_delivery_callers_cannot_request_fewer_permissions(self) -> None:
        mutations = (
            (
                ".github/workflows/preview-agent.yml",
                "      checks: read\n",
                "checks=none",
            ),
            (
                ".github/workflows/deploy-agent.yml",
                "      pull-requests: read\n",
                "pull-requests=none",
            ),
        )
        for relative, removed_permission, expected in mutations:
            with (
                self.subTest(workflow=relative),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = copy_local_governance_fixture(directory)
                workflow = root / relative
                original = workflow.read_text(encoding="utf-8")
                mutated = original.replace(removed_permission, "", 1)
                self.assertNotEqual(original, mutated)
                workflow.write_text(mutated, encoding="utf-8")

                errors = governance.validate_local(root, governance.load_policy())

            self.assertTrue(
                any(
                    "reusable workflow permissions cannot be elevated" in error
                    and expected in error
                    for error in errors
                ),
                errors,
            )

    def test_agent_delivery_rejects_identity_mapping_and_build_reuse_mutations(
        self,
    ) -> None:
        mutations = (
            (
                "builder",
                ".github/workflows/agent-image-build.yml",
                "${{ steps.delivery_identity.outputs.service_account }}",
                "agent-prod-deployer@festive-ally-503605-v7.iam.gserviceaccount.com",
            ),
            (
                "deployer",
                ".github/workflows/agent-release.yml",
                "${{ steps.delivery_identity.outputs.service_account }}",
                "agent-runtime@festive-ally-503605-v7.iam.gserviceaccount.com",
            ),
            (
                "provider",
                ".github/workflows/agent-image-build.yml",
                "${{ steps.delivery_identity.outputs.workload_identity_provider }}",
                "projects/72919926064/locations/global/"
                "workloadIdentityPools/github/providers/github-production",
            ),
            (
                "tag-reuse",
                ".github/workflows/agent-image-build.yml",
                "docker buildx build \\\n",
                'docker buildx imagetools inspect "$image_tag" \\\n',
            ),
            (
                "environment-gate",
                ".github/workflows/agent-release.yml",
                "    environment: ${{ inputs.environment }}",
                "    environment: Agent Preview",
            ),
            (
                "deploy-order",
                ".github/workflows/preview-agent.yml",
                "    needs:\n      - build",
                "    needs:\n      - unrelated",
            ),
        )
        for label, relative, old, new in mutations:
            with (
                self.subTest(mutation=label),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = copy_local_governance_fixture(directory)
                workflow = root / relative
                original = workflow.read_text(encoding="utf-8")
                mutated = original.replace(old, new, 1)
                self.assertNotEqual(original, mutated)
                workflow.write_text(mutated, encoding="utf-8")

                errors = governance.validate_local(root, governance.load_policy())

            self.assertTrue(
                any(
                    relative in error and "exact workflow AST differs" in error
                    for error in errors
                ),
                errors,
            )

    def test_agent_delivery_rejects_identity_validator_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            validator = root / governance.AGENT_DELIVERY_IDENTITY_SCRIPT
            validator.write_text(
                validator.read_text(encoding="utf-8").replace(
                    "agent-preview-image-builder",
                    "agent-image-builder",
                    1,
                ),
                encoding="utf-8",
            )

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(
                "exact reviewed target/phase identity selector" in error
                for error in errors
            ),
            errors,
        )

    def test_agent_delivery_rejects_release_candidate_validator_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            validator = root / governance.AGENT_RELEASE_CANDIDATE_SCRIPT
            original = validator.read_text(encoding="utf-8")
            mutated = original.replace(
                "REQUIRED_PRODUCTION_CHECKS = frozenset("
                '{"ci/check", "protocol/compat", "wiki/verify"})',
                'REQUIRED_PRODUCTION_CHECKS = frozenset({"ci/check"})',
                1,
            )
            self.assertNotEqual(original, mutated)
            validator.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(
                "exact reviewed post-approval release candidate gate" in error
                for error in errors
            ),
            errors,
        )

    def assert_agent_ci_job_mutation_rejected(
        self,
        replacements: tuple[tuple[str, str], ...],
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            workflow = root / ".github/workflows/ci.yml"
            original = workflow.read_text(encoding="utf-8")
            agent_start = original.index("\n  agent:\n") + 1
            agent_end = original.index("\n  eval:\n", agent_start)
            agent_section = original[agent_start:agent_end]
            for old, new in replacements:
                before = agent_section
                agent_section = agent_section.replace(old, new, 1)
                self.assertNotEqual(before, agent_section)
            mutated = original[:agent_start] + agent_section + original[agent_end:]
            workflow.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any("job 'agent' exact job AST differs" in error for error in errors),
            errors,
        )

    def assert_eval_workflow_mutation_rejected(
        self,
        *,
        workflow_name: str,
        replacements: tuple[tuple[str, str], ...],
        expected_error: str,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            workflow = root / ".github/workflows" / workflow_name
            original = workflow.read_text(encoding="utf-8")
            prefix = ""
            suffix = ""
            mutated = original
            if workflow_name == "ci.yml":
                eval_start = original.index("  eval:\n")
                eval_end = original.index("\n  infra:\n", eval_start)
                prefix = original[:eval_start]
                mutated = original[eval_start:eval_end]
                suffix = original[eval_end:]
            for old, new in replacements:
                before = mutated
                mutated = mutated.replace(old, new, 1)
                self.assertNotEqual(before, mutated)
            workflow.write_text(prefix + mutated + suffix, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(expected_error in error for error in errors),
            errors,
        )

    def test_eval_ci_exact_ast_rejects_gate_and_order_weakening(self) -> None:
        mutations = {
            "lock-check": (
                ("        run: uv lock --check\n", "        run: uv lock\n"),
            ),
            "frozen": (
                (
                    "uv sync --frozen --package syshin0116-dev-eval",
                    "uv sync --package syshin0116-dev-eval",
                ),
            ),
            "dataset-check": (("          --check\n", ""),),
            "dataset-validate": (
                (
                    "uv run --frozen --package syshin0116-dev-eval blogeval validate",
                    "echo validate",
                ),
            ),
            "second-sweep": (
                (
                    '            "$RUNNER_TEMP/eval-results-second"\n',
                    "",
                ),
            ),
            "recursive-diff": (
                (
                    "          diff --no-dereference --recursive \\\n",
                    "          diff \\\n",
                ),
            ),
            "publication-linux-amd64-build": (
                (
                    "            --platform linux/amd64 \\\n",
                    "            --platform linux/arm64 \\\n",
                ),
            ),
            "condition": (
                (
                    "if: needs.changes.outputs.eval == 'true'",
                    "if: false",
                ),
            ),
            "continue-on-error": (
                (
                    "      - name: Verify the workspace lockfile is current\n",
                    "      - name: Verify the workspace lockfile is current\n"
                    "        continue-on-error: true\n",
                ),
            ),
        }
        for label, replacements in mutations.items():
            with self.subTest(label=label):
                self.assert_eval_workflow_mutation_rejected(
                    workflow_name="ci.yml",
                    replacements=replacements,
                    expected_error="job 'eval' exact AST differs",
                )

    def test_eval_publication_exact_ast_rejects_untrusted_identity_inputs(self) -> None:
        mutations = {
            "non-main": (
                (
                    "if: github.ref == 'refs/heads/main'",
                    "if: always()",
                ),
            ),
            "environment": (("    environment: Evaluation Publication\n", ""),),
            "caller-image": (
                (
                    "IMAGE_DIGEST: ${{ steps.image.outputs.digest }}",
                    "IMAGE_DIGEST: ${{ env.BLOGEVAL_IMAGE_DIGEST }}",
                ),
            ),
            "tag-execution": (
                (
                    '            "$IMAGE_DIGEST" \\\n',
                    '            "blogeval-candidate:$GITHUB_SHA" \\\n',
                ),
            ),
            "attestation": (
                (
                    "actions/attest@f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6",
                    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
                ),
            ),
        }
        for label, replacements in mutations.items():
            with self.subTest(label=label):
                self.assert_eval_workflow_mutation_rejected(
                    workflow_name="eval-publication.yml",
                    replacements=replacements,
                    expected_error="exact workflow AST differs",
                )

    def test_agent_ci_exact_job_surface_rejects_every_unreviewed_key(self) -> None:
        header = (
            "  agent:\n"
            "    name: ci/agent\n"
            "    if: always()\n"
            "    needs:\n"
            "      - changes\n"
            "    runs-on: ubuntu-latest\n"
            "    timeout-minutes: 30\n"
        )
        env = (
            "    env:\n"
            "      AEGRA_POSTGRES_TEST_URL: "
            "postgresql://postgres@localhost:5432/aegra_ci\n"
            "      AGENT_AUTH_SECRET: ci-only-agent-secret-ci-only-agent-secret\n"
        )
        postgres_image = (
            "    services:\n"
            "      postgres:\n"
            "        image: postgres:17@sha256:"
            "a426e44bac0b759c95894d68e1a0ac03ecc20b619f498a91aae373bf06d8508d\n"
        )
        mutations = {
            "name": ((header, header.replace("name: ci/agent", "name: ci/agent-v2")),),
            "condition": ((header, header.replace("if: always()", "if: success()")),),
            "needs": ((header, header.replace("- changes", "- web")),),
            "runner": (
                (
                    header,
                    header.replace("runs-on: ubuntu-latest", "runs-on: self-hosted"),
                ),
            ),
            "timeout": (
                (header, header.replace("timeout-minutes: 30", "timeout-minutes: 31")),
            ),
            "container-and-uv-project": (
                (
                    header,
                    header + "    container: attacker.invalid/agent:latest\n",
                ),
                (
                    env,
                    env + "      UV_PROJECT: ../web\n",
                ),
            ),
            "services": (
                (
                    postgres_image,
                    postgres_image.replace(
                        "postgres:17@sha256:"
                        "a426e44bac0b759c95894d68e1a0ac03ecc20b619f498a91aae373bf06d8508d",
                        "attacker.invalid/service:latest",
                    ),
                ),
            ),
            "strategy": (
                (
                    header,
                    header + "    strategy:\n" + "      fail-fast: false\n",
                ),
            ),
            "environment": (
                (
                    header,
                    header + "    environment: Production\n",
                ),
            ),
        }
        for label, replacements in mutations.items():
            with self.subTest(label=label):
                self.assert_agent_ci_job_mutation_rejected(replacements)

    def test_agent_ci_postgres_gate_rejects_unreviewed_mutations(self) -> None:
        mutations = {
            "removed-test-url": (
                (
                    "      AEGRA_POSTGRES_TEST_URL: "
                    "postgresql://postgres@localhost:5432/aegra_ci\n",
                    "",
                ),
            ),
            "database-version": (
                (
                    "        image: postgres:17@sha256:"
                    "a426e44bac0b759c95894d68e1a0ac03ecc20b619f498a91aae373bf06d8508d\n",
                    "        image: postgres:16\n",
                ),
            ),
            "database-name": (
                (
                    "          POSTGRES_DB: aegra_ci\n",
                    "          POSTGRES_DB: postgres\n",
                ),
            ),
            "authentication-mode": (
                (
                    "          POSTGRES_HOST_AUTH_METHOD: trust\n",
                    "          POSTGRES_HOST_AUTH_METHOD: reject\n",
                ),
            ),
            "published-port": (
                ('          - "5432:5432"\n', '          - "15432:5432"\n'),
            ),
            "health-command": (
                (
                    '          --health-cmd "pg_isready -U postgres -d aegra_ci"\n',
                    '          --health-cmd "true"\n',
                ),
            ),
            "health-retries": (
                ("          --health-retries 5\n", "          --health-retries 1\n"),
            ),
        }
        for label, replacements in mutations.items():
            with self.subTest(label=label):
                self.assert_agent_ci_job_mutation_rejected(replacements)

    def test_agent_ci_container_smoke_rejects_unreviewed_mutations(self) -> None:
        mutations = {
            "cleanup-trap": (("          trap cleanup EXIT\n", ""),),
            "cleanup-logs": (
                (
                    '              docker container logs "$container_name" || true\n',
                    "",
                ),
            ),
            "migration-host-network": (
                (
                    "            --rm \\\n"
                    "            --network host \\\n"
                    "            --entrypoint python \\\n",
                    "            --rm \\\n"
                    "            --network bridge \\\n"
                    "            --entrypoint python \\\n",
                ),
            ),
            "migration-entrypoint": (
                ("            -m agent.migrate\n", "            -m agent.graph\n"),
            ),
            "runtime-host-network": (
                (
                    '            --name "$container_name" \\\n'
                    "            --network host \\\n",
                    '            --name "$container_name" \\\n'
                    "            --network bridge \\\n",
                ),
            ),
            "production-mode": (
                (
                    "            --env ENV_MODE=PRODUCTION \\\n",
                    "            --env ENV_MODE=LOCAL \\\n",
                ),
            ),
            "startup-migrations": (
                (
                    "            --env REDIS_BROKER_ENABLED=false \\\n"
                    "            --env RUN_MIGRATIONS_ON_STARTUP=false \\\n",
                    "            --env REDIS_BROKER_ENABLED=false \\\n"
                    "            --env RUN_MIGRATIONS_ON_STARTUP=true \\\n",
                ),
            ),
            "readiness": (
                (
                    "                http://127.0.0.1:8080/ready\n",
                    "                http://127.0.0.1:8080/live\n",
                ),
            ),
            "unauthenticated-command": (
                (
                    '          test "$unauthenticated_status" = "401"\n',
                    '          test "$unauthenticated_status" = "200"\n',
                ),
            ),
        }
        for label, replacements in mutations.items():
            with self.subTest(label=label):
                self.assert_agent_ci_job_mutation_rejected(replacements)

    def test_agent_ci_exact_step_inventory_rejects_action_mutations(self) -> None:
        checkout = (
            "      - uses: "
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 "
            "# v7.0.1\n"
            "        with:\n"
            "          persist-credentials: false\n"
            "      - name: Fail closed if change detection failed\n"
        )
        setup_python = (
            "      - uses: "
            "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 "
            "# v7.0.0\n"
            "        if: needs.changes.outputs.agent == 'true'\n"
            "        with:\n"
            '          python-version: "3.12"\n'
        )
        setup_uv = (
            "      - uses: "
            "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 "
            "# v9.0.0\n"
            "        if: needs.changes.outputs.agent == 'true'\n"
            "        with:\n"
            '          version: "0.11.29"\n'
            "          checksum: "
            "04f8b82f5d47f0512dcd32c67a4a6f16a0ea27c81537c338fd0ad6b23cebe829\n"
            "          enable-cache: true\n"
            "          cache-dependency-glob: uv.lock\n"
        )
        mutations = {
            "checkout-ref": (
                (
                    checkout,
                    checkout.replace(
                        "          persist-credentials: false\n",
                        "          persist-credentials: false\n          ref: main\n",
                    ),
                ),
            ),
            "checkout-repository": (
                (
                    checkout,
                    checkout.replace(
                        "          persist-credentials: false\n",
                        "          persist-credentials: false\n"
                        "          repository: attacker/repository\n",
                    ),
                ),
            ),
            "checkout-path": (
                (
                    checkout,
                    checkout.replace(
                        "          persist-credentials: false\n",
                        "          persist-credentials: false\n          path: agent\n",
                    ),
                ),
            ),
            "action-replacement": (
                (
                    setup_python,
                    setup_python.replace(
                        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                        "actions/cache@" + "a" * 40,
                    ),
                ),
            ),
            "moved-action": (
                (
                    setup_python + setup_uv,
                    setup_uv + setup_python,
                ),
            ),
            "deleted-action": ((setup_python, ""),),
            "extra-action": (
                (
                    checkout,
                    checkout.replace(
                        "      - name: Fail closed if change detection failed\n",
                        "      - uses: "
                        "actions/checkout@"
                        "3d3c42e5aac5ba805825da76410c181273ba90b1 "
                        "# v7.0.1\n"
                        "        with:\n"
                        "          persist-credentials: false\n"
                        "      - name: Fail closed if change detection failed\n",
                    ),
                ),
            ),
            "with-change": (
                (
                    setup_python,
                    setup_python.replace(
                        'python-version: "3.12"',
                        'python-version: "3.13"',
                    ),
                ),
            ),
            "if-change": (
                (
                    setup_uv,
                    setup_uv.replace(
                        "if: needs.changes.outputs.agent == 'true'",
                        "if: 'false'",
                    ),
                ),
            ),
            "name-change": (
                (
                    setup_python,
                    setup_python.replace(
                        "      - uses: actions/setup-python@",
                        "      - name: unreviewed setup\n"
                        "        uses: actions/setup-python@",
                    ),
                ),
            ),
        }
        for label, replacements in mutations.items():
            with self.subTest(label=label):
                self.assert_agent_ci_job_mutation_rejected(replacements)

    def test_agent_ci_rejects_extra_local_composite_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            action = root / ".github/actions/unreviewed/action.yml"
            action.parent.mkdir(parents=True)
            action.write_text(
                """
name: unreviewed
runs:
  using: composite
  steps:
    - shell: bash
      run: uv run pytest -q
""".lstrip(),
                encoding="utf-8",
            )
            workflow = root / ".github/workflows/ci.yml"
            original = workflow.read_text(encoding="utf-8")
            old = (
                "      - name: Verify the workspace lockfile is current\n"
                "        if: needs.changes.outputs.agent == 'true'\n"
            )
            new = (
                "      - uses: ./.github/actions/unreviewed\n"
                "        if: needs.changes.outputs.agent == 'true'\n" + old
            )
            mutated = original.replace(old, new, 1)
            self.assertNotEqual(original, mutated)
            workflow.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any("job 'agent' exact job AST differs" in error for error in errors),
            errors,
        )

    def test_agent_ci_requires_lock_check_before_frozen_install(self) -> None:
        mutations = {
            "removed": (
                "      - name: Verify the workspace lockfile is current\n"
                "        if: needs.changes.outputs.agent == 'true'\n"
                "        run: uv lock --check\n",
                "",
            ),
            "after-install": (
                "      - name: Verify the workspace lockfile is current\n"
                "        if: needs.changes.outputs.agent == 'true'\n"
                "        run: uv lock --check\n"
                "      - if: needs.changes.outputs.agent == 'true'\n"
                "        run: >-\n"
                "          uv sync --frozen --package syshin0116-dev-agent "
                "--all-extras --dev\n",
                "      - if: needs.changes.outputs.agent == 'true'\n"
                "        run: >-\n"
                "          uv sync --frozen --package syshin0116-dev-agent "
                "--all-extras --dev\n"
                "      - name: Verify the workspace lockfile is current\n"
                "        if: needs.changes.outputs.agent == 'true'\n"
                "        run: uv lock --check\n",
            ),
            "comment-spoof": (
                "        run: uv lock --check\n",
                "        run: '# uv lock --check'\n",
            ),
            "quoted-string-spoof": (
                "        run: uv lock --check\n",
                '        run: echo "uv lock --check"\n',
            ),
        }
        for label, (old, new) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = copy_local_governance_fixture(directory)
                workflow = root / ".github/workflows/ci.yml"
                original = workflow.read_text(encoding="utf-8")
                mutated = original.replace(old, new, 1)
                self.assertNotEqual(original, mutated)
                workflow.write_text(mutated, encoding="utf-8")

                errors = governance.validate_local(root, governance.load_policy())

                self.assertTrue(
                    any(
                        "job 'agent' exact job AST differs" in error for error in errors
                    ),
                    errors,
                )

    def test_agent_ci_rejects_non_frozen_or_misplaced_uv_run_flag(self) -> None:
        mutations = {
            "missing": (
                "uv run --frozen --package syshin0116-dev-agent ruff check",
                "uv run --package syshin0116-dev-agent ruff check",
            ),
            "passed-to-child-command": (
                "uv run --frozen --package syshin0116-dev-agent ruff check",
                "uv run --package syshin0116-dev-agent ruff --frozen check",
            ),
            "quoted-shell": (
                "uv run --frozen --package syshin0116-dev-agent ruff check",
                'bash -c "uv run ruff check"',
            ),
        }
        for label, (old, new) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = copy_local_governance_fixture(directory)
                workflow = root / ".github/workflows/ci.yml"
                original = workflow.read_text(encoding="utf-8")
                mutated = original.replace(old, new, 1)
                self.assertNotEqual(original, mutated)
                workflow.write_text(mutated, encoding="utf-8")

                errors = governance.validate_local(root, governance.load_policy())

                self.assertTrue(
                    any(
                        "job 'agent' exact job AST differs" in error for error in errors
                    ),
                    errors,
                )

    def test_agent_ci_requires_exact_frozen_uv_run_inventory(self) -> None:
        mutations = {
            "variable-executable": (
                "uv run --frozen --package syshin0116-dev-agent "
                "--all-extras pytest -q agent/tests",
                "$UV run --frozen --package syshin0116-dev-agent "
                "--all-extras pytest -q agent/tests",
            ),
            "command-variable-executable": (
                "uv run --frozen --package syshin0116-dev-agent "
                "--all-extras pytest -q agent/tests",
                'command "$UV" run --frozen --package syshin0116-dev-agent '
                "--all-extras pytest -q agent/tests",
            ),
            "unscoped-pytest": (
                "--all-extras pytest -q agent/tests",
                "--all-extras pytest -q",
            ),
            "deleted-pytest": (
                "      - if: needs.changes.outputs.agent == 'true'\n"
                "        run: >-\n"
                "          uv run --frozen --package syshin0116-dev-agent "
                "--all-extras pytest -q agent/tests\n",
                "",
            ),
            "renamed-child-command": (
                "uv run --frozen --package syshin0116-dev-agent ruff check",
                "uv run --frozen --package syshin0116-dev-agent ruff lint",
            ),
            "extra-run": (
                "      - if: needs.changes.outputs.agent == 'true'\n"
                "        run: >-\n"
                "          uv run --frozen --package syshin0116-dev-agent "
                "--all-extras pytest -q agent/tests\n",
                "      - if: needs.changes.outputs.agent == 'true'\n"
                "        run: uv run --frozen "
                "--package syshin0116-dev-agent python -V\n"
                "      - if: needs.changes.outputs.agent == 'true'\n"
                "        run: >-\n"
                "          uv run --frozen --package syshin0116-dev-agent "
                "--all-extras pytest -q agent/tests\n",
            ),
        }
        for label, (old, new) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = copy_local_governance_fixture(directory)
                workflow = root / ".github/workflows/ci.yml"
                original = workflow.read_text(encoding="utf-8")
                mutated = original.replace(old, new, 1)
                self.assertNotEqual(original, mutated)
                workflow.write_text(mutated, encoding="utf-8")

                errors = governance.validate_local(root, governance.load_policy())

                self.assertTrue(
                    any(
                        "job 'agent' exact job AST differs" in error for error in errors
                    ),
                    errors,
                )

    def test_agent_ci_rejects_indirect_runs_and_execution_overrides(self) -> None:
        mutations = {
            "extra-indirect-run": (
                "      - if: needs.changes.outputs.agent == 'true'\n"
                "        run: >-\n"
                "          uv run --frozen --package syshin0116-dev-agent "
                "--all-extras pytest -q agent/tests\n",
                "      - if: needs.changes.outputs.agent == 'true'\n"
                '        run: \'U=uv; "$U" run --all-extras '
                "pytest -q agent/tests'\n"
                "      - if: needs.changes.outputs.agent == 'true'\n"
                "        run: >-\n"
                "          uv run --frozen --package syshin0116-dev-agent "
                "--all-extras pytest -q agent/tests\n",
            ),
            "step-shell": (
                "        run: uv lock --check\n",
                "        run: uv lock --check\n        shell: python\n",
            ),
            "step-env": (
                "        run: uv lock --check\n",
                "        run: uv lock --check\n"
                "        env:\n"
                "          UV_PROJECT: ../web\n",
            ),
            "job-env": (
                "    env:\n"
                "      AEGRA_POSTGRES_TEST_URL: "
                "postgresql://postgres@localhost:5432/aegra_ci\n"
                "      AGENT_AUTH_SECRET: ci-only-agent-secret-ci-only-agent-secret\n",
                "    env:\n"
                "      AEGRA_POSTGRES_TEST_URL: "
                "postgresql://postgres@localhost:5432/aegra_ci\n"
                "      AGENT_AUTH_SECRET: ci-only-agent-secret-ci-only-agent-secret\n"
                "      UV_PROJECT: ../web\n",
            ),
            "job-shell": (
                "  agent:\n"
                "    name: ci/agent\n"
                "    if: always()\n"
                "    needs:\n"
                "      - changes\n"
                "    runs-on: ubuntu-latest\n"
                "    timeout-minutes: 30\n"
                "    services:\n",
                "  agent:\n"
                "    name: ci/agent\n"
                "    if: always()\n"
                "    needs:\n"
                "      - changes\n"
                "    runs-on: ubuntu-latest\n"
                "    timeout-minutes: 30\n"
                "    defaults:\n"
                "      run:\n"
                "        shell: python\n"
                "    services:\n",
            ),
        }
        for label, (old, new) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = copy_local_governance_fixture(directory)
                workflow = root / ".github/workflows/ci.yml"
                original = workflow.read_text(encoding="utf-8")
                mutated = original.replace(old, new, 1)
                self.assertNotEqual(original, mutated)
                workflow.write_text(mutated, encoding="utf-8")

                errors = governance.validate_local(root, governance.load_policy())

                self.assertTrue(
                    any(
                        "job 'agent' exact job AST differs" in error
                        or "env must remain exactly" in error
                        or "defaults are forbidden" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_agent_ci_rejects_non_frozen_install_and_disabled_lock_check(self) -> None:
        mutations = {
            "non-frozen-install": (
                "uv sync --frozen --package syshin0116-dev-agent --all-extras --dev",
                "uv sync --package syshin0116-dev-agent --all-extras --dev",
            ),
            "disabled-lock-check": (
                "      - name: Verify the workspace lockfile is current\n"
                "        if: needs.changes.outputs.agent == 'true'\n",
                "      - name: Verify the workspace lockfile is current\n"
                "        if: 'false'\n",
            ),
        }
        for label, (old, new) in mutations.items():
            with self.subTest(label=label):
                self.assert_agent_ci_job_mutation_rejected(((old, new),))

    def test_policy_rejects_an_overbroad_main_ruleset(self) -> None:
        policy = json.loads(json.dumps(governance.load_policy()))
        policy["main"]["ruleset"]["conditions"]["ref_name"]["include"] = ["~ALL"]

        errors = governance.validate_local(REPO_ROOT, policy)

        self.assertTrue(
            any(
                "policy.main.ruleset" in error and "~DEFAULT_BRANCH" in error
                for error in errors
            )
        )

    def test_policy_rejects_solo_owner_review_deadlock_parameters(self) -> None:
        policy = json.loads(json.dumps(governance.load_policy()))
        policy["main"]["pull_request_parameters"][
            "required_review_thread_resolution"
        ] = True

        errors = governance.validate_local(REPO_ROOT, policy)

        self.assertTrue(
            any(
                "complete solo-owner contract" in error
                and "pull_request_parameters" in error
                for error in errors
            )
        )

    def test_policy_identity_and_api_baseline_is_hardcoded(self) -> None:
        mutations = (
            ("repository", "renamed-owner/renamed-repository", "policy.repository"),
            ("api_version", "2022-11-28", "policy.api_version"),
        )
        for field, value, expected_error in mutations:
            with self.subTest(field=field):
                policy = json.loads(json.dumps(governance.load_policy()))
                policy[field] = value

                errors = governance.validate_local(REPO_ROOT, policy)

                self.assertTrue(
                    any(expected_error in error for error in errors),
                    errors,
                )

        policy = json.loads(json.dumps(governance.load_policy()))
        policy["main"]["ref"] = "refs/heads/develop"

        errors = governance.validate_local(REPO_ROOT, policy)

        self.assertTrue(any("policy.main.ref" in error for error in errors), errors)

    def test_required_check_manifest_baseline_is_exact(self) -> None:
        mutations = (
            ("context", "renamed/check"),
            ("integration_id", 999),
            ("workflow", ".github/workflows/dependency-audit.yml"),
            ("job", "renamed-job"),
            ("triggers", {"pull_request": {}}),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                policy = json.loads(json.dumps(governance.load_policy()))
                policy["main"]["required_checks"][0][field] = value

                errors = governance.validate_local(REPO_ROOT, policy)

                self.assertTrue(
                    any(
                        "required_checks differs from the complete reviewed baseline"
                        in error
                        for error in errors
                    ),
                    errors,
                )

    def test_actions_policy_object_and_keyset_are_exact(self) -> None:
        mutations = (
            ("value", {"enabled": False}),
            ("type", {"enabled": 1}),
            ("missing", {"sha_pinning_required": None}),
            ("extra", {"undocumented_setting": True}),
        )
        for label, mutation in mutations:
            with self.subTest(label=label):
                policy = json.loads(json.dumps(governance.load_policy()))
                if label == "missing":
                    del policy["actions"]["sha_pinning_required"]
                else:
                    policy["actions"].update(mutation)

                errors = governance.validate_local(REPO_ROOT, policy)

                self.assertTrue(
                    any("policy.actions differs exactly" in error for error in errors),
                    errors,
                )

    def test_environment_policy_reviewer_and_name_mutations_are_exact(self) -> None:
        def mutate_preview_reviewer(policy: dict[str, object]) -> None:
            policy["environments"]["Preview"]["protection_rules"] = [
                {
                    "type": "required_reviewers",
                    "prevent_self_review": False,
                    "reviewers": [{"type": "User", "login": "syshin0116"}],
                }
            ]

        def mutate_remove_reviewer(policy: dict[str, object]) -> None:
            policy["environments"]["Production"]["protection_rules"][0][
                "reviewers"
            ] = []

        def mutate_reviewer_type(policy: dict[str, object]) -> None:
            policy["environments"]["Production"]["protection_rules"][0]["reviewers"][
                0
            ] = {"type": "Team", "slug": "owners"}

        def mutate_reviewer_identity(policy: dict[str, object]) -> None:
            policy["environments"]["Production"]["protection_rules"][0]["reviewers"][0][
                "login"
            ] = "another-owner"

        def mutate_duplicate_reviewer(policy: dict[str, object]) -> None:
            reviewers = policy["environments"]["Production"]["protection_rules"][0][
                "reviewers"
            ]
            reviewers.append(json.loads(json.dumps(reviewers[0])))

        def mutate_self_review(policy: dict[str, object]) -> None:
            policy["environments"]["Production"]["protection_rules"][0][
                "prevent_self_review"
            ] = True

        def mutate_eval_publication_admin_bypass(policy: dict[str, object]) -> None:
            policy["environments"]["Evaluation Publication"]["can_admins_bypass"] = True

        def mutate_eval_publication_reviewer(policy: dict[str, object]) -> None:
            policy["environments"]["Evaluation Publication"]["protection_rules"][0][
                "reviewers"
            ] = []

        def mutate_staging(policy: dict[str, object]) -> None:
            policy["environments"]["Staging"] = {
                "can_admins_bypass": True,
                "deployment_branch_policy": None,
                "branch_policies": [],
                "protection_rules": [],
            }

        mutations = (
            ("preview-reviewer", mutate_preview_reviewer),
            ("reviewer-removal", mutate_remove_reviewer),
            ("reviewer-type", mutate_reviewer_type),
            ("reviewer-identity", mutate_reviewer_identity),
            ("reviewer-duplicate", mutate_duplicate_reviewer),
            ("self-review", mutate_self_review),
            ("eval-publication-admin-bypass", mutate_eval_publication_admin_bypass),
            ("eval-publication-reviewer", mutate_eval_publication_reviewer),
            ("staging", mutate_staging),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                policy = json.loads(json.dumps(governance.load_policy()))
                mutate(policy)

                errors = governance.validate_local(REPO_ROOT, policy)

                self.assertTrue(
                    any(
                        "policy.environments differs from the complete reviewed"
                        in error
                        for error in errors
                    ),
                    errors,
                )

    def test_dependabot_policy_cannot_move_with_yaml_without_baseline_review(
        self,
    ) -> None:
        mutations = (
            (
                "vulnerability-alerts",
                ("vulnerability_alerts_enabled",),
                False,
            ),
            (
                "security-updates-enabled",
                ("automated_security_fixes", "enabled"),
                False,
            ),
            (
                "security-updates-paused",
                ("automated_security_fixes", "paused"),
                True,
            ),
            (
                "repository-security-status",
                ("repository_security_updates_status",),
                "disabled",
            ),
            (
                "version-update-schedule",
                ("updates", 0, "schedule", "day"),
                "tuesday",
            ),
        )
        for label, path, value in mutations:
            with self.subTest(label=label):
                policy = json.loads(json.dumps(governance.load_policy()))
                target = policy["dependabot"]
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value

                errors = governance.validate_local(REPO_ROOT, policy)

                self.assertTrue(
                    any("policy.dependabot differs" in error for error in errors),
                    errors,
                )

    def test_policy_keeps_status_checks_enforced_on_existing_main(self) -> None:
        policy = json.loads(json.dumps(governance.load_policy()))
        policy["main"]["required_status_checks_parameters"][
            "do_not_enforce_on_create"
        ] = True

        errors = governance.validate_local(REPO_ROOT, policy)

        self.assertTrue(
            any(
                "required_status_checks_parameters" in error
                and "do_not_enforce_on_create" in error
                for error in errors
            )
        )

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
    steps:
      - run: echo protocol
  wiki:
    name: wiki/verify
    steps:
      - run: echo wiki
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

    def test_flow_mapping_step_uses_is_checked_in_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/flow.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                'jobs: {check: {steps: [{"uses": actions/checkout@v7}]}}\n',
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(any("actions/checkout@v7" in error for error in errors))

    def test_explicit_quoted_step_uses_is_checked_in_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/explicit.yml"
            workflow.parent.mkdir(parents=True)
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

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(any("actions/checkout@v7" in error for error in errors))

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

    def test_valid_local_composite_action_reference_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/local.yml"
            action = root / ".github/actions/check/action.yml"
            workflow.parent.mkdir(parents=True)
            action.parent.mkdir(parents=True)
            workflow.write_text(
                """
jobs:
  check:
    steps:
      - uses: ./.github/actions/check
""".lstrip(),
                encoding="utf-8",
            )
            action.write_text(
                """
name: check
runs:
  using: composite
  steps:
    - run: echo ok
      shell: bash
""".lstrip(),
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertEqual([], errors)

    def test_nested_workflow_is_rejected_as_non_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / ".github/workflows/nested/check.yaml"
            nested.parent.mkdir(parents=True)
            nested.write_text(
                "jobs: {check: {steps: [{run: echo ignored}]}}\n",
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(
            any(
                ".github/workflows/nested/check.yaml" in error
                and "not supported by GitHub" in error
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
                """
jobs:
  check:
    steps:
      - uses: ./.github/actions/outer
""".lstrip(),
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

    def test_ordinary_uses_keys_are_not_treated_as_invocations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/ordinary.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
on:
  workflow_call:
    inputs:
      uses:
        required: false
        type: string
env:
  uses: actions/checkout@v7
jobs:
  check:
    env:
      uses: actions/checkout@v7
    steps:
      - run: echo ok
""".lstrip(),
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertEqual([], errors)

    def test_job_level_uses_cannot_target_an_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/inverted.yml"
            action = root / ".github/actions/check/action.yml"
            workflow.parent.mkdir(parents=True)
            action.parent.mkdir(parents=True)
            workflow.write_text(
                "jobs: {check: {uses: ./.github/actions/check}}\n",
                encoding="utf-8",
            )
            action.write_text(
                """
name: check
runs:
  using: composite
  steps:
    - run: echo ok
      shell: bash
""".lstrip(),
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(any("job-level uses must target" in error for error in errors))

    def test_step_level_uses_cannot_target_a_reusable_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            caller = root / ".github/workflows/caller.yml"
            reusable = root / ".github/workflows/reusable.yml"
            caller.parent.mkdir(parents=True)
            caller.write_text(
                """
jobs:
  check:
    steps:
      - uses: ./.github/workflows/reusable.yml
""".lstrip(),
                encoding="utf-8",
            )
            reusable.write_text(
                """
on:
  workflow_call:
jobs:
  called:
    steps:
      - run: echo called
""".lstrip(),
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(
            any("step-level uses cannot target" in error for error in errors)
        )

    def test_valid_top_level_reusable_workflow_reference_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            caller = root / ".github/workflows/caller.yml"
            reusable = root / ".github/workflows/reusable.yml"
            caller.parent.mkdir(parents=True)
            caller.write_text(
                "jobs: {check: {uses: ./.github/workflows/reusable.yml}}\n",
                encoding="utf-8",
            )
            reusable.write_text(
                """
on:
  workflow_call:
jobs:
  called:
    steps:
      - run: echo called
""".lstrip(),
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertEqual([], errors)

    def test_reusable_workflow_without_workflow_call_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            caller = root / ".github/workflows/caller.yml"
            reusable = root / ".github/workflows/reusable.yml"
            caller.parent.mkdir(parents=True)
            caller.write_text(
                "jobs: {check: {uses: ./.github/workflows/reusable.yml}}\n",
                encoding="utf-8",
            )
            reusable.write_text(
                """
on:
  workflow_dispatch:
jobs:
  called:
    steps:
      - run: echo called
""".lstrip(),
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(any("lacks on.workflow_call" in error for error in errors))

    def test_repository_action_must_be_composite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            action = root / ".github/actions/node/action.yml"
            action.parent.mkdir(parents=True)
            action.write_text(
                """
name: node action
runs:
  using: node20
  main: index.js
""".lstrip(),
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(
            any("runs.using must be 'composite'" in error for error in errors)
        )

    def test_external_action_and_reusable_workflow_positions_pass(self) -> None:
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/external.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                f"""
jobs:
  action:
    steps:
      - uses: actions/checkout@{sha}
  reusable:
    uses: owner/repo/.github/workflows/reusable.yml@{sha}
""".lstrip(),
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertEqual([], errors)

    def test_external_reusable_workflow_must_use_a_full_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/external.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """
jobs:
  reusable:
    uses: owner/repo/.github/workflows/reusable.yml@main
""".lstrip(),
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(
            any(
                "job-level uses must reference" in error
                and "reusable.yml@main" in error
                for error in errors
            )
        )

    def test_external_job_action_and_step_workflow_inversions_fail(self) -> None:
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/external-inverted.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                f"""
jobs:
  action-as-job:
    uses: actions/checkout@{sha}
  workflow-as-step:
    steps:
      - uses: owner/repo/.github/workflows/reusable.yml@{sha}
""".lstrip(),
                encoding="utf-8",
            )

            _, errors = governance.validate_repository_yaml_references(root)

        self.assertTrue(
            any("job-level uses must reference" in error for error in errors)
        )
        self.assertTrue(
            any("step-level uses cannot target" in error for error in errors)
        )

    def test_local_action_target_escape_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflow = root / ".github/workflows/check.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "jobs: {check: {steps: [{uses: ./../outside}]}}\n",
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
                "jobs: {check: {steps: [{uses: ./.github/actions/missing}]}}\n",
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
        audit_commands = [
            governance._scalar_value(node, context="dependency audit run").strip()
            for node in governance._nodes_for_mapping_key(document.root, "run")
            if isinstance(node, governance.ScalarNode)
        ]
        self.assertEqual(
            1,
            audit_commands.count(governance.DEPENDENCY_WEB_AUDIT_COMMAND),
        )

    def test_dependency_audit_setup_mutations_are_rejected(self) -> None:
        mutations = (
            (
                "checksum",
                "04f8b82f5d47f0512dcd32c67a4a6f16a0ea27c81537c338fd0ad6b23cebe829",
                "0" * 64,
            ),
            (
                "uv-version",
                'version: "0.11.29"',
                'version: "0.11.28"',
            ),
            (
                "setup-python",
                "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                "actions/setup-python@" + "a" * 40,
            ),
            (
                "setup-uv",
                "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9",
                "astral-sh/setup-uv@" + "b" * 40,
            ),
        )
        for label, old, new in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = copy_local_governance_fixture(directory)
                workflow = root / ".github/workflows/dependency-audit.yml"
                original = workflow.read_text(encoding="utf-8")
                mutated = original.replace(old, new, 1)
                self.assertNotEqual(original, mutated)
                workflow.write_text(mutated, encoding="utf-8")

                errors = governance.validate_local(root, governance.load_policy())

            self.assertTrue(
                any(
                    "dependency audit agent setup differs" in error for error in errors
                ),
                errors,
            )

    def test_dependency_audit_upstream_and_aggregation_mutations_are_rejected(
        self,
    ) -> None:
        mutations = (
            (
                "script",
                "python scripts/upstream_version_audit.py",
                "python scripts/smoke.py",
                "job 'upstream' exact AST differs",
            ),
            (
                "summary",
                '          --summary "$GITHUB_STEP_SUMMARY"\n',
                "",
                "job 'upstream' exact AST differs",
            ),
            (
                "needs",
                "      - upstream\n",
                "",
                "job 'check' exact AST differs",
            ),
            (
                "result",
                "          UPSTREAM_RESULT: ${{ needs.upstream.result }}\n",
                "",
                "job 'check' exact AST differs",
            ),
        )
        for label, old, new, expected in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = copy_local_governance_fixture(directory)
                workflow = root / ".github/workflows/dependency-audit.yml"
                original = workflow.read_text(encoding="utf-8")
                mutated = original.replace(old, new, 1)
                self.assertNotEqual(original, mutated)
                workflow.write_text(mutated, encoding="utf-8")

                errors = governance.validate_local(root, governance.load_policy())

            self.assertTrue(
                any(expected in error for error in errors),
                errors,
            )

    def test_dependency_audit_missing_upstream_script_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            (root / governance.UPSTREAM_VERSION_AUDIT_SCRIPT).unlink()

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(
                "upstream script must be a regular repository file" in error
                for error in errors
            ),
            errors,
        )

    def test_dependency_audit_target_contract_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            script = root / governance.UPSTREAM_VERSION_AUDIT_SCRIPT
            original = script.read_text(encoding="utf-8")
            mutated = original.replace(
                'package="langchain-quickjs"',
                'package="not-the-reviewed-package"',
                1,
            )
            self.assertNotEqual(original, mutated)
            script.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any("exact reviewed target/source contract" in error for error in errors),
            errors,
        )

    def test_repository_wide_uv_toolchain_mutations_are_rejected(self) -> None:
        mutations = (
            (
                "root-required-version",
                "pyproject.toml",
                'required-version = "==0.11.29"',
                'required-version = ">=0.11.29"',
                "tool.uv.required-version must equal",
            ),
            (
                "docker-version",
                "Dockerfile",
                'ARG UV_VERSION="0.11.29"',
                'ARG UV_VERSION="0.11.28"',
                "UV_VERSION ARG must remain exact",
            ),
            (
                "ci-unpinned-version",
                ".github/workflows/ci.yml",
                '          version: "0.11.29"\n',
                "",
                "version must equal",
            ),
            (
                "protocol-wrong-checksum",
                ".github/workflows/protocol-compat.yml",
                governance.UV_CHECKSUM,
                "0" * 64,
                "checksum must equal",
            ),
            (
                "release-wrong-action",
                ".github/workflows/agent-release.yml",
                governance.SETUP_UV_ACTION,
                "astral-sh/setup-uv@" + "b" * 40,
                "must use exact action",
            ),
        )
        for label, relative, old, new, expected in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = copy_local_governance_fixture(directory)
                path = root / relative
                original = path.read_text(encoding="utf-8")
                mutated = original.replace(old, new, 1)
                self.assertNotEqual(original, mutated)
                path.write_text(mutated, encoding="utf-8")
                documents, reference_errors = (
                    governance.validate_repository_yaml_references(root)
                )
                self.assertEqual([], reference_errors)

                errors = governance.validate_uv_toolchain_contract(root, documents)

            self.assertTrue(any(expected in error for error in errors), errors)

    def test_dependabot_groups_match_the_exact_policy(self) -> None:
        policy = governance.load_policy()

        self.assertEqual(
            [],
            governance.validate_dependabot_grouping(
                REPO_ROOT / ".github/dependabot.yml",
                policy,
            ),
        )

    def test_dependabot_monthly_rollups_include_each_ecosystem(self) -> None:
        document = governance.load_yaml_document(REPO_ROOT / ".github/dependabot.yml")
        groups = governance._normalized_dependabot_groups(document)

        for group in (
            groups["bun:/web:web-monthly"],
            groups["uv:/:python-monthly"],
            groups["github-actions:/:actions-monthly"],
        ):
            self.assertEqual(["*"], group["patterns"])
            self.assertEqual([], group["exclude_patterns"])
            self.assertEqual(["major", "minor", "patch"], group["update_types"])

    def test_dependabot_group_pattern_mutation_is_rejected(self) -> None:
        policy = governance.load_policy()
        original = (REPO_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            mutated = Path(directory) / "dependabot.yml"
            mutated.write_text(
                original.replace('          - "*"\n', "", 1),
                encoding="utf-8",
            )

            errors = governance.validate_dependabot_grouping(mutated, policy)

        self.assertTrue(
            any("patterns" in error and "web-monthly" in error for error in errors)
        )

    def test_dependabot_full_contract_field_mutations_are_rejected(self) -> None:
        original = (REPO_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
        mutations = (
            ("version-change", "version: 2\n", "version: 1\n"),
            ("version-removal", "version: 2\n", ""),
            (
                "schedule-interval",
                '      interval: "monthly"\n',
                '      interval: "daily"\n',
            ),
            ("schedule-time", '      time: "04:00"\n', '      time: "05:00"\n'),
            (
                "schedule-timezone",
                '      timezone: "Asia/Seoul"\n',
                '      timezone: "UTC"\n',
            ),
            (
                "open-limit-removal",
                "    open-pull-requests-limit: 1\n",
                "",
            ),
            (
                "open-limit-change",
                "    open-pull-requests-limit: 1\n",
                "    open-pull-requests-limit: 2\n",
            ),
            ("cooldown-removal", "      semver-major-days: 14\n", ""),
            (
                "cooldown-change",
                "      semver-patch-days: 3\n",
                "      semver-patch-days: 4\n",
            ),
            (
                "cooldown-extra",
                "      semver-patch-days: 3\n",
                "      semver-patch-days: 3\n      unsupported-days: 5\n",
            ),
            (
                "group-value-change",
                '        applies-to: "version-updates"\n',
                '        applies-to: "security-updates"\n',
            ),
        )
        policy = governance.load_policy()
        for label, old, new in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                mutated_text = original.replace(old, new, 1)
                self.assertNotEqual(original, mutated_text)
                mutated = Path(directory) / "dependabot.yml"
                mutated.write_text(mutated_text, encoding="utf-8")

                errors = governance.validate_dependabot_configuration(
                    mutated,
                    policy,
                )

                self.assertTrue(errors, label)

    def test_dependabot_update_removal_duplicate_and_extra_are_rejected(self) -> None:
        original = (REPO_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
        bun_start = original.index('  - package-ecosystem: "bun"')
        npm_start = original.index('  - package-ecosystem: "npm"')
        actions_start = original.index('  - package-ecosystem: "github-actions"')
        bun_update = original[bun_start:npm_start].rstrip()
        mutations = {
            "removal": original[:actions_start].rstrip() + "\n",
            "duplicate": original.rstrip() + "\n\n" + bun_update + "\n",
            "extra": (
                original.rstrip()
                + "\n\n"
                + bun_update.replace(
                    'package-ecosystem: "bun"',
                    'package-ecosystem: "docker"',
                    1,
                )
                .replace('directory: "/web"', 'directory: "/extra"', 1)
                .replace("web-monthly:", "extra-monthly:", 1)
                + "\n"
            ),
            "identity-change": original.replace(
                '    directory: "/web"\n',
                '    directory: "/renamed-web"\n',
                1,
            ),
        }
        policy = governance.load_policy()
        for label, text in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                mutated = Path(directory) / "dependabot.yml"
                mutated.write_text(text, encoding="utf-8")

                errors = governance.validate_dependabot_configuration(
                    mutated,
                    policy,
                )

                self.assertTrue(errors, label)
                self.assertTrue(
                    any(
                        "update identities differ exactly" in error
                        or "duplicate Dependabot update" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_dependabot_group_removal_duplicate_and_extra_are_rejected(self) -> None:
        original = (REPO_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
        groups_start = original.index("    groups:\n      web-monthly:")
        npm_start = original.index('\n  - package-ecosystem: "npm"')
        group_block = original[groups_start + len("    groups:\n") : npm_start].rstrip()
        mutations = {
            "removal": (
                original[:groups_start] + "    groups: {}\n" + original[npm_start + 1 :]
            ),
            "duplicate": (
                original[:npm_start] + "\n" + group_block + original[npm_start:]
            ),
            "extra": (
                original[:npm_start]
                + "\n"
                + group_block.replace("web-monthly:", "web-extra:", 1)
                + original[npm_start:]
            ),
        }
        policy = governance.load_policy()
        for label, text in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                mutated = Path(directory) / "dependabot.yml"
                mutated.write_text(text, encoding="utf-8")

                errors = governance.validate_dependabot_configuration(
                    mutated,
                    policy,
                )

                self.assertTrue(errors, label)

    def test_duplicate_required_check_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            duplicate = root / ".github/workflows/duplicate.yml"
            duplicate.write_text(
                """
jobs:
  duplicate:
    name: ci/check
    steps:
      - run: echo duplicate
""".lstrip(),
                encoding="utf-8",
            )

            errors = governance.validate_local(root, governance.load_policy())

        self.assertIn(
            "local: required check 'ci/check' must be emitted by exactly "
            "one job, found 2",
            errors,
        )

    def test_nested_fake_emitter_cannot_replace_top_level_required_job(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            ci = root / ".github/workflows/ci.yml"
            original = ci.read_text(encoding="utf-8")
            mutated = original.replace(
                "    name: ci/check\n",
                "    name: ci/check-renamed\n",
                1,
            )
            self.assertNotEqual(original, mutated)
            ci.write_text(mutated, encoding="utf-8")
            nested = root / ".github/workflows/fake/ci.yml"
            nested.parent.mkdir(parents=True)
            nested.write_text(
                """
jobs:
  check:
    name: ci/check
    steps:
      - run: echo fake
""".lstrip(),
                encoding="utf-8",
            )

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(
                "nested workflow YAML is not supported by GitHub" in error
                and ".github/workflows/fake/ci.yml" in error
                for error in errors
            )
        )
        self.assertIn(
            "local: required check 'ci/check' must be emitted by exactly "
            "one job, found 0",
            errors,
        )
        self.assertTrue(
            any(
                ".github/workflows/ci.yml:check is named 'ci/check-renamed'" in error
                for error in errors
            )
        )

    def test_required_context_in_wrong_job_id_fails_emitter_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            workflow = root / ".github/workflows/protocol-compat.yml"
            original = workflow.read_text(encoding="utf-8")
            mutated = original.replace(
                "  protocol-compat:\n",
                "  renamed-protocol-job:\n",
                1,
            )
            self.assertNotEqual(original, mutated)
            workflow.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertIn(
            "local: required check 'protocol/compat' emitter job "
            "'protocol-compat' is missing from "
            ".github/workflows/protocol-compat.yml",
            errors,
        )

    def test_schedule_only_required_workflow_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            workflow = root / ".github/workflows/wiki-verify.yml"
            original = workflow.read_text(encoding="utf-8")
            mutated = re.sub(
                r"(?ms)^on:\n.*?^permissions:",
                (
                    "on:\n"
                    "  schedule:\n"
                    '    - cron: "17 18 * * 0"\n'
                    "  workflow_dispatch:\n\n"
                    "permissions:"
                ),
                original,
                count=1,
            )
            self.assertNotEqual(original, mutated)
            workflow.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(
                "required check 'wiki/verify' triggers are" in error
                and "'schedule'" in error
                for error in errors
            )
        )

    def test_pull_request_paths_filter_on_required_workflow_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            workflow = root / ".github/workflows/protocol-compat.yml"
            original = workflow.read_text(encoding="utf-8")
            mutated = original.replace(
                "  pull_request:\n",
                '  pull_request:\n    paths:\n      - "protocol/**"\n',
                1,
            )
            self.assertNotEqual(original, mutated)
            workflow.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(
                "required check 'protocol/compat' triggers are" in error
                and "'paths': ['protocol/**']" in error
                for error in errors
            )
        )

    def test_required_aggregate_with_needs_must_use_always(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            workflow = root / ".github/workflows/ci.yml"
            original = workflow.read_text(encoding="utf-8")
            mutated = original.replace(
                "  check:\n    name: ci/check\n    if: always()\n",
                "  check:\n    name: ci/check\n",
                1,
            )
            self.assertNotEqual(original, mutated)
            workflow.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(
                "job 'check' has needs and must use if: always()" in error
                for error in errors
            )
        )

    def test_required_dependency_with_skipping_condition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            workflow = root / ".github/workflows/ci.yml"
            original = workflow.read_text(encoding="utf-8")
            mutated = original.replace(
                "  web:\n    name: ci/web\n    if: always()\n",
                ("  web:\n    name: ci/web\n    if: github.actor == 'nobody'\n"),
                1,
            )
            self.assertNotEqual(original, mutated)
            workflow.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(
                "job 'web' can skip required-check creation" in error
                for error in errors
            )
        )
        self.assertTrue(
            any(
                "job 'web' has needs and must use if: always()" in error
                for error in errors
            )
        )

    def test_required_jobs_and_steps_forbid_continue_on_error(self) -> None:
        mutations = (
            (
                "emitter-job",
                "  check:\n    name: ci/check\n",
                "  check:\n    name: ci/check\n    continue-on-error: false\n",
                "job 'check'",
            ),
            (
                "dependency-job",
                "  changes:\n    name: ci/changes\n",
                "  changes:\n    name: ci/changes\n    continue-on-error: true\n",
                "job 'changes'",
            ),
            (
                "emitter-step",
                "      - name: Require every Application CI job to pass\n",
                (
                    "      - name: Require every Application CI job to pass\n"
                    "        continue-on-error: false\n"
                ),
                "job 'check' step[0]",
            ),
            (
                "dependency-step",
                (
                    "      - uses: "
                    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 "
                    "# v7.0.1\n"
                    "        with:\n"
                    "          fetch-depth: 0\n"
                ),
                (
                    "      - uses: "
                    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 "
                    "# v7.0.1\n"
                    "        continue-on-error: false\n"
                    "        with:\n"
                    "          fetch-depth: 0\n"
                ),
                "job 'changes' step[0]",
            ),
        )
        for label, old, new, expected_context in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = copy_local_governance_fixture(directory)
                workflow = root / ".github/workflows/ci.yml"
                original = workflow.read_text(encoding="utf-8")
                mutated = original.replace(old, new, 1)
                self.assertNotEqual(original, mutated)
                workflow.write_text(mutated, encoding="utf-8")

                errors = governance.validate_local(root, governance.load_policy())

                self.assertTrue(
                    any(
                        expected_context in error
                        and "continue-on-error" in error
                        and "required-check execution path" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_required_emitter_and_needs_jobs_forbid_reusable_workflows(
        self,
    ) -> None:
        external = "example/required-checks/.github/workflows/check.yml@" + "a" * 40
        mutations = (
            ("emitter-local", "emitter", "./.github/workflows/required-call.yml"),
            ("emitter-external", "emitter", external),
            ("needs-local", "needs", "./.github/workflows/required-call.yml"),
            ("needs-external", "needs", external),
        )
        for label, location, reference in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = copy_local_governance_fixture(directory)
                if reference.startswith("./"):
                    reusable = root / ".github/workflows/required-call.yml"
                    reusable.write_text(
                        """
name: required call
on:
  workflow_call:
jobs:
  skipped:
    if: github.actor == 'nobody'
    runs-on: ubuntu-latest
    steps:
      - run: echo skipped
""".lstrip(),
                        encoding="utf-8",
                    )
                ci = root / ".github/workflows/ci.yml"
                original = ci.read_text(encoding="utf-8")
                if location == "emitter":
                    replacement = (
                        "  check:\n"
                        "    name: ci/check\n"
                        "    if: always()\n"
                        "    needs:\n"
                        "      - changes\n"
                        "      - web\n"
                        "      - agent\n"
                        "      - eval\n"
                        f"    uses: {reference}\n"
                    )
                    mutated = re.sub(
                        r"(?ms)^  check:\n.*\Z",
                        replacement,
                        original,
                        count=1,
                    )
                    expected_context = "job 'check'"
                else:
                    mutated = original.replace(
                        "  check:\n",
                        f"  delegated-required:\n    uses: {reference}\n\n  check:\n",
                        1,
                    ).replace(
                        "    needs:\n      - changes\n      - web\n",
                        "    needs:\n"
                        "      - delegated-required\n"
                        "      - changes\n"
                        "      - web\n",
                        1,
                    )
                    expected_context = "job 'delegated-required'"
                self.assertNotEqual(original, mutated)
                ci.write_text(mutated, encoding="utf-8")

                errors = governance.validate_local(root, governance.load_policy())

                self.assertTrue(
                    any(
                        expected_context in error
                        and reference in error
                        and "job-level uses is forbidden" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_reachable_local_composite_actions_forbid_continue_on_error(
        self,
    ) -> None:
        manifests = {
            ".github/actions/required/outer/action.yml": """
name: outer
runs:
  using: composite
  steps:
    - uses: ./.github/actions/required/inner
""",
            ".github/actions/required/inner/action.yml": """
name: inner
runs:
  using: composite
  steps:
    - run: echo required
      shell: bash
      continue-on-error: false
""",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            for relative, content in manifests.items():
                manifest = root / relative
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text(content.lstrip(), encoding="utf-8")
            workflow = root / ".github/workflows/ci.yml"
            original = workflow.read_text(encoding="utf-8")
            mutated = original.replace(
                "    steps:\n      - name: Require every Application CI job to pass\n",
                "    steps:\n"
                "      - uses: ./.github/actions/required/outer\n"
                "      - name: Require every Application CI job to pass\n",
                1,
            )
            self.assertNotEqual(original, mutated)
            workflow.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(
                ".github/actions/required/inner/action.yml" in error
                and "continue-on-error" in error
                for error in errors
            ),
            errors,
        )

    def test_directly_reachable_composite_action_forbids_continue_on_error(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = copy_local_governance_fixture(directory)
            action = root / ".github/actions/required/action.yml"
            action.parent.mkdir(parents=True)
            action.write_text(
                """
name: required
runs:
  using: composite
  steps:
    - run: echo required
      shell: bash
      continue-on-error: true
""".lstrip(),
                encoding="utf-8",
            )
            workflow = root / ".github/workflows/ci.yml"
            original = workflow.read_text(encoding="utf-8")
            mutated = original.replace(
                "    steps:\n      - name: Require every Application CI job to pass\n",
                "    steps:\n"
                "      - uses: ./.github/actions/required\n"
                "      - name: Require every Application CI job to pass\n",
                1,
            )
            self.assertNotEqual(original, mutated)
            workflow.write_text(mutated, encoding="utf-8")

            errors = governance.validate_local(root, governance.load_policy())

        self.assertTrue(
            any(
                ".github/actions/required/action.yml" in error
                and "continue-on-error" in error
                for error in errors
            ),
            errors,
        )

    def test_reachable_reusable_workflows_forbid_continue_on_error(self) -> None:
        workflow_mutations = (
            (
                "reusable-job",
                """
name: delegated
on:
  workflow_call:
jobs:
  delegated:
    continue-on-error: false
    runs-on: ubuntu-latest
    steps:
      - run: echo delegated
""",
                "job 'delegated'",
            ),
            (
                "reusable-step",
                """
name: delegated
on:
  workflow_call:
jobs:
  delegated:
    runs-on: ubuntu-latest
    steps:
      - run: echo delegated
        continue-on-error: true
""",
                "job 'delegated' step[0]",
            ),
            (
                "nested-reusable-step",
                """
name: delegated
on:
  workflow_call:
jobs:
  delegated:
    uses: ./.github/workflows/required-nested.yml
""",
                "required-nested.yml",
            ),
        )
        for label, delegated_content, expected_context in workflow_mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = copy_local_governance_fixture(directory)
                delegated = root / ".github/workflows/required-delegated.yml"
                delegated.write_text(delegated_content.lstrip(), encoding="utf-8")
                if label == "nested-reusable-step":
                    nested = root / ".github/workflows/required-nested.yml"
                    nested.write_text(
                        """
name: nested
on:
  workflow_call:
jobs:
  nested:
    runs-on: ubuntu-latest
    steps:
      - run: echo nested
        continue-on-error: false
""".lstrip(),
                        encoding="utf-8",
                    )
                ci = root / ".github/workflows/ci.yml"
                original = ci.read_text(encoding="utf-8")
                mutated = original.replace(
                    "  check:\n",
                    (
                        "  delegated-required:\n"
                        "    uses: ./.github/workflows/required-delegated.yml\n\n"
                        "  check:\n"
                    ),
                    1,
                ).replace(
                    "  check:\n"
                    "    name: ci/check\n"
                    "    if: always()\n"
                    "    needs:\n"
                    "      - changes\n",
                    "  check:\n"
                    "    name: ci/check\n"
                    "    if: always()\n"
                    "    needs:\n"
                    "      - delegated-required\n"
                    "      - changes\n",
                    1,
                )
                self.assertNotEqual(original, mutated)
                ci.write_text(mutated, encoding="utf-8")

                errors = governance.validate_local(root, governance.load_policy())

                self.assertTrue(
                    any(
                        expected_context in error and "continue-on-error" in error
                        for error in errors
                    ),
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

    def test_repository_merge_methods_must_match_pull_request_rule(self) -> None:
        responses = desired_live_responses()
        repository = json.loads(json.dumps(responses[""]))
        repository["allow_rebase_merge"] = False
        responses[""] = repository

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertTrue(
            any(
                "repository merge methods" in error and "'rebase'" in error
                for error in errors
            )
        )

    def test_repository_full_name_rejects_rename_or_redirect(self) -> None:
        for full_name in (
            "syshin0116/renamed.dev",
            "redirect-owner/syshin0116.dev",
        ):
            with self.subTest(full_name=full_name):
                responses = desired_live_responses()
                repository = json.loads(json.dumps(responses[""]))
                repository["full_name"] = full_name
                responses[""] = repository

                errors = governance.verify_live(
                    self.policy,
                    responses.__getitem__,
                )

                self.assertTrue(
                    any(
                        "repository full_name" in error
                        and full_name in error
                        and governance.EXPECTED_REPOSITORY in error
                        for error in errors
                    ),
                    errors,
                )

    def test_default_branch_develop_does_not_make_default_token_target_main(
        self,
    ) -> None:
        responses = desired_live_responses()
        repository = json.loads(json.dumps(responses[""]))
        repository["default_branch"] = "develop"
        responses[""] = repository

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertTrue(
            any("repository default_branch is 'develop'" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any(
                "0 active branch rulesets target refs/heads/main" in error
                for error in errors
            ),
            errors,
        )

    def test_default_branch_token_and_explicit_ref_have_distinct_semantics(
        self,
    ) -> None:
        ruleset = json.loads(json.dumps(desired_live_responses()["rulesets/7"]))
        self.assertFalse(
            governance._ruleset_targets_main(
                ruleset,
                "refs/heads/main",
                "refs/heads/develop",
            )
        )
        ruleset["conditions"]["ref_name"]["include"] = ["refs/heads/main"]
        self.assertTrue(
            governance._ruleset_targets_main(
                ruleset,
                "refs/heads/main",
                "refs/heads/develop",
            )
        )

    def test_pull_request_owned_parameter_mutations_fail_exactly(self) -> None:
        mutations = (
            ("allowed_merge_methods", ["squash"]),
            ("dismiss_stale_reviews_on_push", True),
            (
                "dismissal_restriction",
                {"allowed_actors": [], "enabled": True},
            ),
            ("require_last_push_approval", True),
            ("required_review_thread_resolution", True),
            (
                "required_reviewers",
                [
                    {
                        "file_patterns": ["web/**"],
                        "minimum_approvals": 1,
                        "reviewer": {"id": 17, "type": "Team"},
                    }
                ],
            ),
            ("undocumented_semantic_gate", True),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                responses = desired_live_responses()
                ruleset = json.loads(json.dumps(responses["rulesets/7"]))
                pull_request = next(
                    rule for rule in ruleset["rules"] if rule["type"] == "pull_request"
                )
                pull_request["parameters"][field] = value
                responses["rulesets/7"] = ruleset

                errors = governance.verify_live(
                    self.policy,
                    responses.__getitem__,
                )

                self.assertTrue(
                    any(
                        "main pull-request parameters differ exactly" in error
                        for error in errors
                    )
                )

    def test_api_normalized_disabled_dismissal_restriction_is_omitted(self) -> None:
        responses = desired_live_responses()
        ruleset = json.loads(json.dumps(responses["rulesets/7"]))
        pull_request = next(
            rule for rule in ruleset["rules"] if rule["type"] == "pull_request"
        )
        self.assertNotIn("dismissal_restriction", pull_request["parameters"])

        pull_request["parameters"]["dismissal_restriction"] = {
            "allowed_actors": [],
            "enabled": False,
        }
        responses["rulesets/7"] = ruleset

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertTrue(
            any(
                "main pull-request parameters differ exactly" in error
                for error in errors
            ),
            errors,
        )

    def test_status_check_owned_parameter_mutations_fail_exactly(self) -> None:
        mutations = (
            ("do_not_enforce_on_create", True),
            ("strict_required_status_checks_policy", False),
            ("undocumented_semantic_gate", True),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                responses = desired_live_responses()
                ruleset = json.loads(json.dumps(responses["rulesets/7"]))
                status = next(
                    rule
                    for rule in ruleset["rules"]
                    if rule["type"] == "required_status_checks"
                )
                status["parameters"][field] = value
                responses["rulesets/7"] = ruleset

                errors = governance.verify_live(
                    self.policy,
                    responses.__getitem__,
                )

                self.assertTrue(
                    any(
                        "required-status-check parameters differ exactly" in error
                        for error in errors
                    )
                )

    def test_main_ruleset_owned_identity_is_exact(self) -> None:
        mutations = (
            ("name", "not-main"),
            (
                "conditions",
                {
                    "ref_name": {
                        "include": ["~ALL"],
                        "exclude": [],
                    }
                },
            ),
            ("source", "another-owner/another-repository"),
            ("source_type", "Organization"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                responses = desired_live_responses()
                ruleset = json.loads(json.dumps(responses["rulesets/7"]))
                ruleset[field] = value
                responses["rulesets/7"] = ruleset

                errors = governance.verify_live(
                    self.policy,
                    responses.__getitem__,
                )

                self.assertTrue(
                    any(
                        "ruleset identity/target differs exactly" in error
                        for error in errors
                    )
                )

    def test_non_branch_ruleset_cannot_satisfy_main_contract(self) -> None:
        responses = desired_live_responses()
        ruleset = json.loads(json.dumps(responses["rulesets/7"]))
        ruleset["target"] = "tag"
        responses["rulesets/7"] = ruleset

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertTrue(
            any(
                "0 active branch rulesets target refs/heads/main" in error
                for error in errors
            )
        )

    def test_legacy_main_branch_protection_is_rejected(self) -> None:
        responses = desired_live_responses()
        responses[LEGACY_MAIN_PROTECTION] = governance.ApiResponse(
            payload={"required_status_checks": {}},
            headers={},
            status=200,
        )

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertIn(
            "external: legacy main branch protection exists; rulesets are "
            "the only allowed main protection surface",
            errors,
        )

    def test_legacy_protection_404_requires_exact_absence_message(self) -> None:
        responses = desired_live_responses()
        responses[LEGACY_MAIN_PROTECTION] = governance.ApiResponse(
            payload={"message": "Not Found", "status": "404"},
            headers={},
            status=404,
        )

        with self.assertRaisesRegex(
            governance.GovernanceError,
            "did not confirm an unprotected branch",
        ):
            governance.verify_live(self.policy, responses.__getitem__)

    def test_legacy_protection_query_fails_closed_on_forbidden(self) -> None:
        responses = desired_live_responses()
        responses[LEGACY_MAIN_PROTECTION] = governance.ApiResponse(
            payload={"message": "Resource not accessible"},
            headers={},
            status=403,
        )

        with self.assertRaisesRegex(
            governance.GovernanceError,
            "returned HTTP 403",
        ):
            governance.verify_live(self.policy, responses.__getitem__)

    def test_gh_api_rejects_an_unselected_api_version(self) -> None:
        completed = governance.subprocess.CompletedProcess(
            args=["gh", "api"],
            returncode=0,
            stdout=(
                "HTTP/2.0 200 OK\nX-GitHub-Api-Version-Selected: 2022-11-28\n\n{}\n"
            ),
            stderr="",
        )
        with (
            mock.patch.object(
                governance.subprocess,
                "run",
                return_value=completed,
            ),
            self.assertRaisesRegex(
                governance.GovernanceError,
                "selected version '2022-11-28'",
            ),
        ):
            governance._gh_api(
                "owner/repository",
                "2026-03-10",
                "actions/permissions",
            )

    def test_gh_api_accepts_an_empty_204_response(self) -> None:
        completed = governance.subprocess.CompletedProcess(
            args=["gh", "api"],
            returncode=0,
            stdout=(
                "HTTP/2.0 204 No Content\nX-GitHub-Api-Version-Selected: 2026-03-10\n\n"
            ),
            stderr="",
        )
        with mock.patch.object(
            governance.subprocess,
            "run",
            return_value=completed,
        ):
            response = governance._gh_api(
                "owner/repository",
                "2026-03-10",
                "vulnerability-alerts",
            )

        self.assertEqual(204, response.status)
        self.assertIsNone(response.payload)

    def test_gh_api_rejects_a_body_on_204(self) -> None:
        completed = governance.subprocess.CompletedProcess(
            args=["gh", "api"],
            returncode=0,
            stdout=(
                "HTTP/2.0 204 No Content\n"
                "X-GitHub-Api-Version-Selected: 2026-03-10\n\n{}\n"
            ),
            stderr="",
        )
        with (
            mock.patch.object(
                governance.subprocess,
                "run",
                return_value=completed,
            ),
            self.assertRaisesRegex(
                governance.GovernanceError,
                "returned a body for HTTP 204",
            ),
        ):
            governance._gh_api(
                "owner/repository",
                "2026-03-10",
                "vulnerability-alerts",
            )

    def test_disabled_vulnerability_alerts_are_reported(self) -> None:
        responses = desired_live_responses()
        responses["vulnerability-alerts"] = governance.ApiResponse(
            payload={
                "message": "Vulnerability alerts are disabled.",
                "status": "404",
            },
            headers={},
            status=404,
        )

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertIn(
            "external: Dependabot vulnerability alerts are disabled; expected enabled",
            errors,
        )

    def test_vulnerability_alerts_404_requires_disabled_message(self) -> None:
        responses = desired_live_responses()
        responses["vulnerability-alerts"] = governance.ApiResponse(
            payload={"message": "Not Found", "status": "404"},
            headers={},
            status=404,
        )

        with self.assertRaisesRegex(
            governance.GovernanceError,
            "404 did not confirm that alerts are disabled",
        ):
            governance.verify_live(self.policy, responses.__getitem__)

    def test_vulnerability_alerts_query_fails_closed_on_forbidden(self) -> None:
        responses = desired_live_responses()
        responses["vulnerability-alerts"] = governance.ApiResponse(
            payload={"message": "Resource not accessible"},
            headers={},
            status=403,
        )

        with self.assertRaisesRegex(
            governance.GovernanceError,
            "vulnerability-alerts query returned HTTP 403",
        ):
            governance.verify_live(self.policy, responses.__getitem__)

    def test_vulnerability_alerts_204_requires_no_body(self) -> None:
        responses = desired_live_responses()
        responses["vulnerability-alerts"] = governance.ApiResponse(
            payload={},
            headers={},
            status=204,
        )

        with self.assertRaisesRegex(
            governance.GovernanceError,
            "HTTP 204 response must have no body",
        ):
            governance.verify_live(self.policy, responses.__getitem__)

    def test_automated_security_fixes_object_is_exact(self) -> None:
        mutations = (
            ("disabled", {"enabled": False, "paused": False}),
            ("paused", {"enabled": True, "paused": True}),
            ("missing", {"enabled": True}),
            (
                "extra",
                {
                    "enabled": True,
                    "paused": False,
                    "undocumented_setting": False,
                },
            ),
        )
        for label, payload in mutations:
            with self.subTest(label=label):
                responses = desired_live_responses()
                responses["automated-security-fixes"] = payload

                errors = governance.verify_live(
                    self.policy,
                    responses.__getitem__,
                )

                self.assertTrue(
                    any(
                        "Dependabot security updates differ exactly" in error
                        and f"automated_security_fixes={payload!r}" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_automated_security_fixes_query_fails_closed_on_forbidden(self) -> None:
        responses = desired_live_responses()
        responses["automated-security-fixes"] = governance.ApiResponse(
            payload={"message": "Resource not accessible"},
            headers={},
            status=403,
        )

        with self.assertRaisesRegex(
            governance.GovernanceError,
            "automated-security-fixes query returned HTTP 403",
        ):
            governance.verify_live(self.policy, responses.__getitem__)

    def test_repository_security_updates_status_is_cross_checked(self) -> None:
        responses = desired_live_responses()
        repository = json.loads(json.dumps(responses[""]))
        repository["security_and_analysis"]["dependabot_security_updates"]["status"] = (
            "disabled"
        )
        responses[""] = repository

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertTrue(
            any(
                "Dependabot security updates differ exactly" in error
                and "repository_status='disabled'" in error
                for error in errors
            ),
            errors,
        )

    def test_disabled_security_updates_produce_one_combined_gap(self) -> None:
        responses = desired_live_responses()
        repository = json.loads(json.dumps(responses[""]))
        repository["security_and_analysis"]["dependabot_security_updates"]["status"] = (
            "disabled"
        )
        responses[""] = repository
        responses["automated-security-fixes"] = {
            "enabled": False,
            "paused": False,
        }

        errors = governance.verify_live(self.policy, responses.__getitem__)

        self.assertEqual(
            1,
            sum(
                "Dependabot security updates differ exactly" in error
                for error in errors
            ),
            errors,
        )

    def test_repository_security_updates_status_requires_admin_shape(self) -> None:
        def remove_security_and_analysis(repository: dict[str, object]) -> None:
            del repository["security_and_analysis"]

        def remove_dependabot_status_object(repository: dict[str, object]) -> None:
            repository["security_and_analysis"] = {}

        def remove_status(repository: dict[str, object]) -> None:
            repository["security_and_analysis"]["dependabot_security_updates"] = {}

        mutations = (
            ("security-and-analysis", remove_security_and_analysis),
            ("dependabot-security-updates", remove_dependabot_status_object),
            ("status", remove_status),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                responses = desired_live_responses()
                repository = json.loads(json.dumps(responses[""]))
                mutate(repository)
                responses[""] = repository

                with self.assertRaisesRegex(
                    governance.GovernanceError,
                    "repository-admin read access",
                ):
                    governance.verify_live(
                        self.policy,
                        responses.__getitem__,
                    )

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

    def test_actions_response_object_and_keyset_are_exact(self) -> None:
        mutations = (
            {"enabled": True, "allowed_actions": "all"},
            {
                "enabled": True,
                "allowed_actions": "all",
                "sha_pinning_required": True,
                "undocumented_setting": False,
            },
        )
        for actions in mutations:
            with self.subTest(actions=actions):
                responses = desired_live_responses()
                responses["actions/permissions"] = actions

                errors = governance.verify_live(
                    self.policy,
                    responses.__getitem__,
                )

                self.assertTrue(
                    any(
                        "GitHub Actions permissions differ exactly" in error
                        for error in errors
                    ),
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

    def test_evaluation_publication_environment_drift_is_rejected(self) -> None:
        mutations = (
            ("admin-bypass", "can_admins_bypass", True),
            ("self-review", "prevent_self_review", True),
            ("reviewer", "reviewer-login", "another-owner"),
        )
        for label, field, value in mutations:
            with self.subTest(label=label):
                responses = desired_live_responses()
                path = "environments/Evaluation%20Publication"
                environment = json.loads(json.dumps(responses[path]))
                if field == "reviewer-login":
                    environment["protection_rules"][0]["reviewers"][0]["reviewer"][
                        "login"
                    ] = value
                elif field == "prevent_self_review":
                    environment["protection_rules"][0][field] = value
                else:
                    environment[field] = value
                responses[path] = environment

                errors = governance.verify_live(
                    self.policy,
                    responses.__getitem__,
                )

                self.assertTrue(
                    any(
                        "environment 'Evaluation Publication'" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_evaluation_publication_inventory_must_remain_empty(self) -> None:
        cases = (
            (EVAL_PUBLICATION_SECRETS_PAGE, "secrets"),
            (EVAL_PUBLICATION_VARIABLES_PAGE, "variables"),
        )
        for endpoint, collection in cases:
            with self.subTest(collection=collection):
                responses = desired_live_responses()
                responses[endpoint] = {
                    "total_count": 1,
                    collection: [{"name": "MUST_NOT_APPEAR_IN_OUTPUT"}],
                }

                errors = governance.verify_live(
                    self.policy,
                    responses.__getitem__,
                )

                self.assertTrue(
                    any(
                        f"{collection} differ exactly" in error
                        and "actual_count=1" in error
                        and "expected_count=0" in error
                        for error in errors
                    ),
                    errors,
                )
                self.assertNotIn("MUST_NOT_APPEAR_IN_OUTPUT", "\n".join(errors))

    def test_agent_environment_inventories_are_exact_without_name_leakage(
        self,
    ) -> None:
        cases = (
            (AGENT_PREVIEW_SECRETS_PAGE, "secrets", [], 0, 1),
            (
                AGENT_PREVIEW_SECRETS_PAGE,
                "secrets",
                [
                    {"name": "AGENT_SMOKE_BEARER_TOKEN"},
                    {"name": "MUST_NOT_APPEAR_IN_OUTPUT"},
                ],
                2,
                1,
            ),
            (
                AGENT_PREVIEW_VARIABLES_PAGE,
                "variables",
                [{"name": "MUST_NOT_APPEAR_IN_OUTPUT"}],
                1,
                0,
            ),
            (AGENT_PRODUCTION_SECRETS_PAGE, "secrets", [], 0, 1),
            (
                AGENT_PRODUCTION_VARIABLES_PAGE,
                "variables",
                [{"name": "MUST_NOT_APPEAR_IN_OUTPUT"}],
                1,
                0,
            ),
        )
        for endpoint, collection, inventory, actual_count, expected_count in cases:
            with self.subTest(endpoint=endpoint, collection=collection):
                responses = desired_live_responses()
                responses[endpoint] = {
                    "total_count": actual_count,
                    collection: inventory,
                }

                errors = governance.verify_live(
                    self.policy,
                    responses.__getitem__,
                )

                self.assertTrue(
                    any(
                        f"{collection} differ exactly" in error
                        and f"actual_count={actual_count}" in error
                        and f"expected_count={expected_count}" in error
                        for error in errors
                    ),
                    errors,
                )
                self.assertNotIn("MUST_NOT_APPEAR_IN_OUTPUT", "\n".join(errors))

    def test_evaluation_publication_inventory_api_failure_fails_closed(self) -> None:
        for endpoint in (
            EVAL_PUBLICATION_SECRETS_PAGE,
            EVAL_PUBLICATION_VARIABLES_PAGE,
        ):
            with self.subTest(endpoint=endpoint):
                responses = desired_live_responses()
                responses[endpoint] = governance.ApiResponse(
                    payload={"message": "Forbidden"},
                    headers={},
                    status=403,
                )

                with self.assertRaisesRegex(
                    governance.GovernanceError,
                    "returned HTTP 403",
                ):
                    governance.verify_live(self.policy, responses.__getitem__)

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

    def test_production_reviewer_set_and_type_mutations_are_rejected(self) -> None:
        def remove_reviewers(required_reviewers: dict[str, object]) -> None:
            required_reviewers["reviewers"] = []

        def change_type(required_reviewers: dict[str, object]) -> None:
            required_reviewers["reviewers"] = [
                {
                    "type": "Team",
                    "reviewer": {"slug": "owners"},
                }
            ]

        def duplicate_reviewer(required_reviewers: dict[str, object]) -> None:
            reviewers = required_reviewers["reviewers"]
            reviewers.append(json.loads(json.dumps(reviewers[0])))

        def add_reviewer(required_reviewers: dict[str, object]) -> None:
            required_reviewers["reviewers"].append(
                {
                    "type": "User",
                    "reviewer": {"login": "another-owner"},
                }
            )

        mutations = (
            ("removal", remove_reviewers),
            ("type", change_type),
            ("duplicate", duplicate_reviewer),
            ("extra", add_reviewer),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                responses = desired_live_responses()
                production = json.loads(
                    json.dumps(responses["environments/Production"])
                )
                required_reviewers = production["protection_rules"][0]
                mutate(required_reviewers)
                responses["environments/Production"] = production

                errors = governance.verify_live(
                    self.policy,
                    responses.__getitem__,
                )

                self.assertTrue(
                    any(
                        "environment 'Production' protection rules" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_production_reviewer_rule_removal_extra_and_duplicate_are_rejected(
        self,
    ) -> None:
        for label in ("removal", "extra", "duplicate"):
            with self.subTest(label=label):
                responses = desired_live_responses()
                production = json.loads(
                    json.dumps(responses["environments/Production"])
                )
                reviewer_rule = production["protection_rules"][0]
                if label == "removal":
                    production["protection_rules"] = [production["protection_rules"][1]]
                elif label == "extra":
                    production["protection_rules"].append(
                        {
                            "type": "required_reviewers",
                            "prevent_self_review": False,
                            "reviewers": [
                                {
                                    "type": "User",
                                    "reviewer": {"login": "another-owner"},
                                }
                            ],
                        }
                    )
                else:
                    production["protection_rules"].append(
                        json.loads(json.dumps(reviewer_rule))
                    )
                responses["environments/Production"] = production

                errors = governance.verify_live(
                    self.policy,
                    responses.__getitem__,
                )

                self.assertTrue(
                    any(
                        "environment 'Production' protection rules" in error
                        for error in errors
                    ),
                    errors,
                )

    def test_extra_environment_is_rejected_as_policy_drift(self) -> None:
        responses = desired_live_responses()
        environments = json.loads(json.dumps(responses[ENVIRONMENTS_PAGE]))
        environments["total_count"] = 6
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
        environments["total_count"] = 6
        responses[ENVIRONMENTS_PAGE] = environments

        with self.assertRaisesRegex(
            governance.GovernanceError,
            "total_count is 6",
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

    def test_evaluation_publication_inventory_pagination_fails_closed(self) -> None:
        for endpoint in (
            EVAL_PUBLICATION_SECRETS_PAGE,
            EVAL_PUBLICATION_VARIABLES_PAGE,
        ):
            with self.subTest(endpoint=endpoint):
                responses = desired_live_responses()
                responses[endpoint] = governance.ApiResponse(
                    payload=responses[endpoint],
                    headers={
                        "link": (
                            '<https://api.github.test/inventory?page=2>; rel="next"'
                        )
                    },
                )

                with self.assertRaisesRegex(
                    governance.GovernanceError,
                    "requires pagination",
                ):
                    governance.verify_live(self.policy, responses.__getitem__)

    def test_evaluation_publication_inventory_total_count_fails_closed(self) -> None:
        cases = (
            (EVAL_PUBLICATION_SECRETS_PAGE, "secrets"),
            (EVAL_PUBLICATION_VARIABLES_PAGE, "variables"),
        )
        for endpoint, collection in cases:
            with self.subTest(collection=collection):
                responses = desired_live_responses()
                responses[endpoint] = {
                    "total_count": 1,
                    collection: [],
                }

                with self.assertRaisesRegex(
                    governance.GovernanceError,
                    "total_count is 1",
                ):
                    governance.verify_live(self.policy, responses.__getitem__)


if __name__ == "__main__":
    unittest.main()
