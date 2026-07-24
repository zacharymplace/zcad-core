"""Validation rules for assembly definitions."""

from zcad.assemblies.models import Assembly


def validate_assembly(
    assembly: Assembly,
    *,
    generated_part_names: set[str],
) -> None:
    """Validate an assembly against generated model parts."""
    if not assembly.assembly_id.strip():
        raise ValueError("Assembly ID cannot be empty")

    if not assembly.parts:
        raise ValueError("Assembly must contain at least one part")

    declared_names: list[str] = []

    for part in assembly.parts:
        part.validate()
        declared_names.append(part.name)

    if len(declared_names) != len(set(declared_names)):
        raise ValueError("Assembly part names must be unique")

    declared_set = set(declared_names)

    if assembly.reference_part not in declared_set:
        raise ValueError("Assembly reference part is not declared")

    missing_models = declared_set - generated_part_names

    if missing_models:
        raise ValueError(
            "Assembly references missing generated parts: "
            + ", ".join(sorted(missing_models))
        )

    undeclared_models = generated_part_names - declared_set

    if undeclared_models:
        raise ValueError(
            "Generated parts are missing from assembly: "
            + ", ".join(sorted(undeclared_models))
        )

    for relationship in assembly.relationships:
        relationship.validate()

        if relationship.parent not in declared_set:
            raise ValueError(
                f"Mate parent is not a declared assembly part: {relationship.parent}"
            )

        if relationship.child not in declared_set:
            raise ValueError(
                f"Mate child is not a declared assembly part: {relationship.child}"
            )
