# Introduction

A patch to reduce input and frame processing latency in the Flutter iOS engine.

## Current Patches

| Area | Summary |
| --- | --- |
| Touch input | Remove input buffering that defers events until the next VSync |
| Input and frame requests | Process immediately on the UI thread without unnecessary queue delays |
| iOS 18+ VSync | Use UIUpdateLink to start frames in sync with the UI update cycle |
| Metal rendering | Present frames through a native CAMetalLayer and keep compositing settings fixed |
| Platform Views | Composite Flutter frames and native views in the same transaction |
| Memory cleanup | Release temporary objects after each task on Darwin |
