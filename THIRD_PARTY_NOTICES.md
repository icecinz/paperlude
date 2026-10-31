# Third-party components

Paperlude contains project-specific orchestration, segmentation planning, paper rendering and background-compositing code. Third-party source trees, model weights, virtual environments and build caches are not vendored in this repository.

## SAM 2

- Project: [Meta Segment Anything Model 2](https://github.com/facebookresearch/sam2)
- Pinned source commit: `2b90b9f5ceec907a1c18123530e92e794ad901a4`
- Model: SAM 2.1 Hiera small
- Official checkpoint: `https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt`
- Checkpoint SHA-256: `6d1aa6f30de5c92224f8172114de081d104bbd23dd9dc5c58996f0cad5dc4d38`

The SAM 2 repository states that its principal code and checkpoints are under Apache 2.0. Optional `cc_torch` components have a separate BSD 3-Clause notice; the upstream demo also includes assets with their own terms. Consult the [upstream license](https://github.com/facebookresearch/sam2/blob/2b90b9f5ceec907a1c18123530e92e794ad901a4/LICENSE) and notices when installing or redistributing those components. Paperlude does not redistribute their source or model binaries.

## Other runtime dependencies

PyTorch, torchvision, NumPy, Pillow, OpenCV, SciPy and SAM 2's transitive dependencies are installed separately and retain their respective licenses. `requirements.txt` records the direct versions used by this release. FFmpeg / ffprobe are external executables and must be installed separately; their licensing depends on the build and enabled codecs.

## Media and references

The giraffe demo comes from the local footage supplied for this project. The paper texture was AI-generated for the project. No general reusable-media license is granted with this initial release. Third-party reference films are linked in the documentation rather than copied into the repository.

The project code has not yet been assigned an open-source license. This notice identifies dependencies; it does not replace their licenses or grant rights to unrelated third-party media.
