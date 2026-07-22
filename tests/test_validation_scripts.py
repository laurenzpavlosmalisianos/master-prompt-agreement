"""Single discovery entrypoint for the domain-owned validation test modules."""

from __future__ import annotations

from functools import cmp_to_key
import unittest

from tests.validation_automation_state import AutomationStateTests
from tests.validation_bootstrap_end_to_end import BootstrapEndToEndTests
from tests.validation_bootstrap_runtime import BootstrapRenderingTests
from tests.validation_bootstrap_transactions import BootstrapTransactionTests
from tests.validation_evidence_scope import EvidenceScopeTests
from tests.validation_link_check import LinkCheckTests
from tests.validation_markdown_structure import MarkdownStructureTests
from tests.validation_product_conformance import ProductConformanceTests
from tests.validation_product_manifest import ProductManifestTests
from tests.validation_product_quality import ProductQualityTests
from tests.validation_project_contract_sync import ProjectContractSyncTests
from tests.validation_project_refresh import ProjectRefreshLifecycleTests
from tests.validation_project_runtime import ProjectStateInstanceContextTests
from tests.validation_reference_freshness import ReferenceFreshnessTests
from tests.validation_runtime_compactness import RuntimeCompactnessTests
from tests.validation_safe_io_integrations import SafeIoIntegrationTests
from tests.validation_source_chain import SourceChainTests
from tests.validation_source_deep_research import SourceDeepResearchTests
from tests.validation_source_registry_access import SourceRegistryAccessTests
from tests.validation_url_safety import UrlSafetyTests
from tests.validation_validation_routing import ValidationRoutingTests


_DOMAIN_CASES: tuple[type[unittest.TestCase], ...] = (
    ProductManifestTests,
    ProductQualityTests,
    ProductConformanceTests,
    ReferenceFreshnessTests,
    ValidationRoutingTests,
    LinkCheckTests,
    MarkdownStructureTests,
    SourceRegistryAccessTests,
    SourceDeepResearchTests,
    UrlSafetyTests,
    AutomationStateTests,
    BootstrapEndToEndTests,
    BootstrapRenderingTests,
    BootstrapTransactionTests,
    ProjectStateInstanceContextTests,
    ProjectContractSyncTests,
    ProjectRefreshLifecycleTests,
    RuntimeCompactnessTests,
    SafeIoIntegrationTests,
    SourceChainTests,
    EvidenceScopeTests,
)
def _validate_domain_inventory() -> None:
    """Fail when an exact product validation module is omitted."""

    from scripts import product_manifest

    declared_modules = {
        relative.removeprefix("tests/").removesuffix(".py")
        for relative in product_manifest.PRODUCT_REQUIRED_FILES
        if relative.startswith("tests/validation_")
        and relative != "tests/validation_test_support.py"
    }
    represented_modules = {
        test_case.__module__.rsplit(".", 1)[-1] for test_case in _DOMAIN_CASES
    }
    missing = sorted(declared_modules - represented_modules)
    unknown = sorted(represented_modules - declared_modules)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"unregistered validation modules: {missing}")
        if unknown:
            details.append(f"registered validation modules not found on disk: {unknown}")
        raise RuntimeError("; ".join(details))


def load_tests(
    loader: unittest.TestLoader,
    _standard_tests: unittest.TestSuite,
    _pattern: str | None,
) -> unittest.TestSuite:
    """Assemble every domain once in the original global method-name order."""
    _validate_domain_inventory()
    cases_by_method: dict[str, type[unittest.TestCase]] = {}
    for test_case in _DOMAIN_CASES:
        for method_name in loader.getTestCaseNames(test_case):
            if method_name in cases_by_method:
                raise RuntimeError(f"duplicate validation test method: {method_name}")
            cases_by_method[method_name] = test_case

    method_names = list(cases_by_method)
    comparator = loader.sortTestMethodsUsing
    if comparator is None:
        method_names.sort()
    else:
        method_names.sort(key=cmp_to_key(comparator))

    return unittest.TestSuite(
        cases_by_method[method_name](method_name)
        for method_name in method_names
    )


if __name__ == "__main__":
    unittest.main()
