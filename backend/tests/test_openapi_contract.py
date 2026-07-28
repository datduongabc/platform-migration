import os
import yaml
from app.main import app


def test_openapi_contract():
    """
    Contract Test: Validates that the running FastAPI application's generated
    OpenAPI specification aligns exactly with the contract defined in openapi.yml.
    """
    # Locate openapi.yml at the project root
    current_dir = os.path.dirname(os.path.abspath(__file__))
    openapi_path = os.path.join(current_dir, "..", "..", "openapi.yml")
    openapi_path = os.path.abspath(openapi_path)

    assert os.path.exists(openapi_path), (
        f"openapi.yml contract file not found at {openapi_path}"
    )

    # Load static contract
    with open(openapi_path, "r", encoding="utf-8") as f:
        static_spec = yaml.safe_load(f)

    # Get generated spec from FastAPI app instance
    generated_spec = app.openapi()

    # Verify OpenAPI version format
    assert generated_spec.get("openapi", "").startswith("3."), (
        "Generated OpenAPI version should be 3.x.x"
    )

    # Extract paths from both specs
    static_paths = static_spec.get("paths", {})
    generated_paths = generated_spec.get("paths", {})

    # Perform comparison on paths and methods
    for path, path_item in static_paths.items():
        # Check path existence
        assert path in generated_paths, (
            f"API Contract Violation: Path '{path}' defined in openapi.yml is not implemented in FastAPI"
        )

        # Check HTTP methods under the path
        for method, method_item in path_item.items():
            # Skip Swagger/OpenAPI metadata fields
            if method not in [
                "get",
                "post",
                "put",
                "delete",
                "options",
                "head",
                "patch",
                "trace",
            ]:
                continue

            assert method in generated_paths[path], (
                f"API Contract Violation: Method '{method.upper()}' for path '{path}' is not implemented in FastAPI"
            )

            # Check path/query parameters
            static_params = {p["name"]: p for p in method_item.get("parameters", [])}
            generated_params = {
                p["name"]: p
                for p in generated_paths[path][method].get("parameters", [])
            }

            for param_name, param_spec in static_params.items():
                assert param_name in generated_params, (
                    f"API Contract Violation: Parameter '{param_name}' for '{method.upper()} {path}' "
                    f"is not implemented in FastAPI"
                )
                assert param_spec.get("in") == generated_params[param_name].get("in"), (
                    f"API Contract Violation: Parameter source ('in') mismatch for '{param_name}' "
                    f"in '{method.upper()} {path}'"
                )

            # Check response status codes
            static_responses = method_item.get("responses", {})
            generated_responses = generated_paths[path][method].get("responses", {})

            for status_code in static_responses.keys():
                assert status_code in generated_responses, (
                    f"API Contract Violation: Response status code '{status_code}' for '{method.upper()} {path}' "
                    f"is not defined in FastAPI route implementation"
                )
