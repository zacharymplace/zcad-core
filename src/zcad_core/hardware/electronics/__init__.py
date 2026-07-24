from zcad_core.hardware.electronics.connectors import (
    BoardEdge,
    RectangularConnectorSpec,
)

"""Electronics hardware specifications."""

from zcad_core.hardware.electronics.raspberry_pi import (
    RaspberryPiPico2Spec,
    get_raspberry_pi_pico2,
)

__all__ = [
    "BoardEdge",
    "RaspberryPiPico2Spec",
    "RectangularConnectorSpec",
    "get_raspberry_pi_pico2",
]
