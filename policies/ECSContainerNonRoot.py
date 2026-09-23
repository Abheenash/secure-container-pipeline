"""The pipeline asserts the *image* runs as uid 10001 (docker inspect in CI).
That check passes even if the task definition overrides the user back to root.
This closes the gap in the IaC itself, so the finding surfaces at plan time
rather than at runtime.

Checkov resolves `jsonencode([...])` into a real Python structure rather than a
JSON string, and wraps it in extra lists, so the container list has to be
unwrapped before it can be inspected.
"""
import json

from checkov.common.models.enums import CheckCategories, CheckResult
from checkov.terraform.checks.resource.base_resource_check import BaseResourceCheck

ROOT_USERS = {"", "0", "root", "0:0", "root:root"}


def _containers(value):
    """Return the list of container dicts from whatever shape checkov hands us."""
    # A raw HCL string that checkov could not resolve.
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    # checkov nests the resolved value in one or more single-element lists.
    for _ in range(5):
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], (list, tuple)):
            value = value[0]
        else:
            break
    if isinstance(value, list) and value and all(isinstance(c, dict) for c in value):
        return value
    return None


class ECSContainerNonRoot(BaseResourceCheck):
    def __init__(self):
        super().__init__(
            name="ECS task containers must declare a non-root user",
            id="CKV_SCP_1",
            categories=[CheckCategories.GENERAL_SECURITY],
            supported_resources=["aws_ecs_task_definition"],
        )

    def scan_resource_conf(self, conf):
        containers = _containers(conf.get("container_definitions", [None])[0])
        if containers is None:
            # Never silently pass something we could not read.
            return CheckResult.FAILED
        for c in containers:
            if str(c.get("user", "")).strip().lower() in ROOT_USERS:
                return CheckResult.FAILED
        return CheckResult.PASSED


check = ECSContainerNonRoot()
