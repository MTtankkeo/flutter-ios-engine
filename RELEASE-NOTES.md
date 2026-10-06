Selected official Flutter stable or beta release + iOS latency patch. Includes an arm64 macOS host engine and an arm64 iOS release engine. See `metadata.json` for the exact channel, version, and commit.

The release is published only after an unsigned iOS application builds using the packaged local-engine artifacts. `metadata.json` records the upstream commit, original patch commit, patch checksum, distribution commit, and Xcode version. Verify the archive with its accompanying SHA-256 file.

This checks build compatibility. Touch-to-display latency and platform-view presentation still require testing on physical iOS devices. Simulator/debug/profile artifacts are not included. Link-time optimization is disabled to reduce build memory requirements; compiler optimizations remain enabled.
