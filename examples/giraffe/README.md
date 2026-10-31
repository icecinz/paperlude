# Giraffe demo

This short clip was supplied by the project owner for the Paperlude experiment. It contains several giraffes; the pipeline replaces the isolated giraffe toward the left side of the group.

| Property | Value |
|---|---|
| Duration | 2.05205 s |
| Frames | 123 |
| Size | 3840 × 2160 |
| Frame rate | 60000/1001 |
| Audio | None |
| Analysis crop | x=1050, y=600, width=600, height=1200 |
| Held poses | 8 |
| Key frames | 5, 18, 33, 53, 67, 87, 101, 114 |

Run `python3 tools/fetch_demo.py` from the repository root to download the versioned demo attachment. It creates `source.mov` and `baseline/` here. These larger files are intentionally outside Git history; the download manifest and input fingerprints identify them.

`baseline/` contains the 123 JPEG analysis crops, 123 binary masks, first-frame prompt mask, texture and paper assets, reports, and four reference outputs. The reports describe this particular experiment. They are not benchmarks of general segmentation quality or proof of perfect background repair.

The example outputs use H.264 8-bit 4:2:0. Their original source is 10-bit ProRes. No claim of pixel-perfect preservation after delivery encoding is made.

The reusable paper texture was generated with the built-in image-generation tool, then applied consistently to photographed silhouettes. The model did not redraw the giraffe for each pose. Its prompt was:

> Create a production texture asset: a flat, evenly illuminated scanned sheet of off-white matte photographic printing paper, very subtle fine paper fibers and a faint irregular physical grain, natural warm ivory #eeeade. Full-bleed texture extending to every edge. Straight-on orthographic view, perfectly flat sheet, no perspective, no folds, no curled corners, no border, no shadows, no objects, no text or watermark. Keep brightness extremely even across the sheet so it can be reused as the material of many photographic paper-cutout animation frames. The fibers should be delicate and realistic, not dirty, stained or visibly patterned. Landscape texture.
