# Retention Strategy Evidence

## Status

Accepted architectural direction.

## Existing strategy

The first reusable retention feature uses wide PCB edge clips with:

- 6.0 mm minimum clip width
- 2.5 mm PCB engagement depth
- continuous edge-material validation
- component-clearance validation
- fail-closed metadata publication

## Evidence results

The strategy was evaluated against official STEP evidence.

| Board | Combined qualifying regions | Decision |
| --- | ---: | --- |
| Raspberry Pi Pico 2 | 0 | Unsupported |
| Arduino UNO R4 WiFi | 1 | Unsupported |
| Adafruit Feather RP2040 | 0 | Unsupported |

A region qualifies only when it is both:

1. clear of modeled components within the engagement band; and
2. supported by continuous PCB material.

At least two mechanically balanced regions are required before
production retention metadata may be published.

## Conclusion

The geometry validation layer is promoted as reusable infrastructure.

The existing wide edge-clip feature remains valid but is not treated as
a universal board-retention architecture. It must continue to fail
closed when verified board retention metadata is unavailable.

No tested production board currently qualifies for wide edge clips.

## Second architecture

The next retention architecture is corner capture.

Corner capture is separate from edge clips. It must not weaken,
special-case, or bypass existing edge validation.

The initial design will derive capture locations from verified board
corner geometry and component keepouts.

## Corner-capture requirements

A valid layout must:

- use at least two capture points;
- resist translation in both board-plane axes;
- provide positive vertical retention;
- avoid mounting holes, connectors, components, and keepouts;
- preserve an intentional installation and removal path;
- support explicit manufacturing clearance;
- fail closed when verified corner metadata is unavailable.

## Delivery sequence

1. Typed corner-capture policy and derived artifact.
2. Pure validation and deterministic derivation.
3. Synthetic corner fixtures.
4. Reusable corner geometry feature.
5. Official-board evidence integration.
6. Fastening backend.
7. End-to-end enclosure generation.
8. Fit verification.

Production board metadata must not be published before the geometry,
clearance, and mechanical-balance gates pass.
