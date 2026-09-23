"""An ALB that forwards malformed headers verbatim lets a client smuggle a
request past the load balancer's own parsing. AWS gates this behind an
attribute that defaults to false, so it has to be set explicitly.
"""
from checkov.common.models.enums import CheckCategories, CheckResult
from checkov.terraform.checks.resource.base_resource_value_check import BaseResourceValueCheck


class ALBDropsInvalidHeaders(BaseResourceValueCheck):
    def __init__(self):
        super().__init__(
            name="Application Load Balancers must drop invalid HTTP headers",
            id="CKV_SCP_2",
            categories=[CheckCategories.NETWORKING],
            supported_resources=["aws_lb"],
        )

    def get_inspected_key(self):
        return "drop_invalid_header_fields"

    def get_expected_value(self):
        return True


check = ALBDropsInvalidHeaders()
