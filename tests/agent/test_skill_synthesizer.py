import pytest
from agent.skill_synthesizer import SkillSynthesizer, SynthesizedSkill


def test_sanitize_skill_name():
    assert SkillSynthesizer.sanitize_skill_name("My Super Feature 2.0!") == "my-super-feature-2-0"
    assert SkillSynthesizer.sanitize_skill_name("---complex--skill---") == "complex-skill"
    assert SkillSynthesizer.sanitize_skill_name("") == "custom-skill"


def test_synthesize_skill_formatting():
    skill = SkillSynthesizer.synthesize_skill(
        name="deploy-redis-cluster",
        description="Procedure to spin up a 3-node Redis cluster with TLS.",
        goal="Deploy Redis cluster on Kubernetes",
        steps=[
            "Configure helm values for redis-ha.",
            "Deploy helm chart to production namespace.",
            "Verify cluster node quorum.",
        ],
        commands=[
            "helm repo add bitnami https://charts.bitnami.com/bitnami",
            "helm install redis-cluster bitnami/redis -f values.yaml",
        ],
        pitfalls=[
            "Ensure persistent volume claim sizes match across all 3 nodes.",
        ],
        verification=[
            "redis-cli -c -p 6379 ping returns PONG on all nodes.",
        ],
        tags=["database", "redis", "kubernetes"],
        category="devops",
    )

    assert skill.name == "deploy-redis-cluster"
    assert "name: deploy-redis-cluster" in skill.content
    assert "Procedure to spin up a 3-node Redis cluster" in skill.content
    assert "## Step-by-Step Procedure" in skill.content
    assert "## Key Commands & Code Snippets" in skill.content
    assert "## Pitfalls & Edge Cases" in skill.content
    assert "## Verification Steps" in skill.content
    assert "helm install" in skill.content


def test_extract_from_tool_events():
    tool_events = [
        {"tool_name": "read_file", "args": {"path": "config.yaml"}},
        {"tool_name": "terminal", "args": {"command": "npm install"}},
        {"tool_name": "terminal", "args": {"command": "npm test"}, "result": "Error: test failed on port 3000"},
        {"tool_name": "patch", "args": {"path": "config.yaml"}},
        {"tool_name": "terminal", "args": {"command": "npm test"}, "result": "All 10 tests passing."},
    ]

    skill = SkillSynthesizer.extract_from_tool_events(
        goal="Fix nodejs port conflict in test suite",
        tool_calls=tool_events,
        outcome="success",
    )

    assert skill is not None
    assert "fix-nodejs-port" in skill.name
    assert "npm test" in skill.content
    assert "Handled error during `terminal`" in skill.content
    assert "Verify all modified files" in skill.content
