# Morphicons frame generation

This development-only generator uses `morphicons` 1.7.0 with Lucide 1.28.0
to precompute vector morph frames. JavaScript is not loaded by the
RenderDoc runtime; the Qt frontend consumes the committed SVG frames through
`RDToolButton`.

The first deliberately narrow application is the Texture Viewer `Fit` toggle:
Lucide `maximize` morphs to `minimize`. This four-corner pair was selected over
the reviewed Tabler arrow pair because its subpaths stay visually continuous
through the middle of the Morphicons transition. Separate previous/next
buttons, one-shot commands, passive status marks, and RenderDoc's specialised
shader playback family remain static.

To regenerate from the pinned packages:

```text
npm ci
npm run generate
```

For an already-installed dependency directory, set
`MORPHICONS_NODE_MODULES` to that absolute `node_modules` path before running
the generator.

- Morphicons: https://github.com/guillermolg00/morphicons (MIT)
- Tabler Icons: https://github.com/tabler/tabler-icons (MIT)
- Lucide: https://github.com/lucide-icons/lucide (ISC)
