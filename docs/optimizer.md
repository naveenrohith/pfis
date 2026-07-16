# PFIS Optimization

PFIS optimization means reducing duplicated code, improving query efficiency, and keeping parser logic maintainable.

Current optimization targets:

- Avoid full-table scans in hot parser paths.
- Cache merchant aliases carefully.
- Keep dashboard payloads paginated.
- Remove dead files and generated artifacts.
- Prefer targeted helper extraction over broad rewrites.

Browser-action optimization from the previous project is not applicable.

