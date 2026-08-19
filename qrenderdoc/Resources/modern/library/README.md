# Icon library sources

The Modern Light icon generator reuses selected, same-semantic 24×24 outline
geometry from **Tabler Icons 3.46.0**. The exact upstream SVGs are vendored in
`tabler-3.46.0/outline/` so generation is deterministic and does not require a
network connection.

- Project: https://tabler.io/icons
- Source: https://github.com/tabler/tabler-icons
- Version: 3.46.0
- License: MIT (`tabler-3.46.0/LICENSE`)

Only icons listed by `TABLER_ICONS` in `../generate_modern_icons.py` are used.
RenderDoc-specific controls and ambiguous legacy semantics remain locally
drawn. The generated runtime SVGs use RenderDoc's existing stroke and colour
policy rather than copying Tabler's presentation attributes.
