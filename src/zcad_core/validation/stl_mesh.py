"""Strict binary STL topology and bounded point occupancy queries; no repair."""

import math
import struct
from collections import Counter
from dataclasses import dataclass
from functools import cached_property


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b, strict=True))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


@dataclass(frozen=True)
class STLMesh:
    """Exact float32 vertices welded by equality, without tolerance repair."""

    triangles: tuple

    def vertical_clearance(self, x, y, z_min, z_max):
        """Check a closed vertical segment for surface contact or solid occupancy.

        No lateral displacement or repair. Contact, including coplanar contact,
        is conservative failure. Midpoint occupancy detects a fully buried line.
        """
        tolerance = 1e-7
        if not all(math.isfinite(v) for v in (x, y, z_min, z_max)) or z_min >= z_max:
            raise ValueError("Expected finite XY and increasing finite Z interval")
        contacts = []
        for a, b, c in self.triangles:
            if (
                x < min(a[0], b[0], c[0]) - tolerance
                or x > max(a[0], b[0], c[0]) + tolerance
                or y < min(a[1], b[1], c[1]) - tolerance
                or y > max(a[1], b[1], c[1]) + tolerance
                or z_min > max(a[2], b[2], c[2]) + tolerance
                or z_max < min(a[2], b[2], c[2]) - tolerance
            ):
                continue
            ex, ey = b[0] - a[0], b[1] - a[1]
            fx, fy = c[0] - a[0], c[1] - a[1]
            determinant = ex * fy - ey * fx
            if determinant == 0:
                # A vertical facet projects to a segment. Reject
                # possible contact conservatively using its projected edges.
                near = False
                for start, end in ((a, b), (b, c), (c, a)):
                    dx, dy = end[0] - start[0], end[1] - start[1]
                    length2 = dx * dx + dy * dy
                    t = (
                        0
                        if length2 == 0
                        else max(
                            0,
                            min(
                                1, ((x - start[0]) * dx + (y - start[1]) * dy) / length2
                            ),
                        )
                    )
                    if (
                        math.hypot(x - start[0] - t * dx, y - start[1] - t * dy)
                        <= tolerance
                    ):
                        near = True
                        break
                if near:
                    contacts.append({"kind": "coplanar"})
                continue
            u = ((x - a[0]) * fy - (y - a[1]) * fx) / determinant
            v = (ex * (y - a[1]) - ey * (x - a[0])) / determinant
            if min(u, v, 1 - u - v) < -1e-9:
                continue
            z = a[2] + u * (b[2] - a[2]) + v * (c[2] - a[2])
            if z_min - tolerance <= z <= z_max + tolerance:
                contacts.append({"kind": "surface", "z_mm": z})
        occupied = None if contacts else self.contains((x, y, (z_min + z_max) / 2))
        return {
            "clear": not contacts and not occupied,
            "surface_contact_count": len(contacts),
            "contacts": contacts[:16],
            "contacts_truncated": len(contacts) > 16,
            "midpoint_occupied": occupied,
            "coordinate_tolerance_mm": tolerance,
        }

    @cached_property
    def rays(self):
        prepared = []
        for direction in ((0.137, 0.319, 1.0), (0.271, 1.0, 0.173)):
            rows = []
            for a, b, c in self.triangles:
                e1, e2 = sub(b, a), sub(c, a)
                h = cross(direction, e2)
                d = dot(e1, h)
                if abs(d) >= 1e-12:
                    rows.append(
                        (
                            a,
                            tuple(v / d for v in h),
                            tuple(v / d for v in cross(e1, direction)),
                            tuple(v / d for v in cross(e1, e2)),
                        )
                    )
            prepared.append(rows)
        return prepared

    def contains(self, point):
        """Ray parity with deterministic alternate rays for edge ambiguity."""
        answers = []
        for rows in self.rays:
            hits = 0
            ambiguous = False
            for a, h, q, normal in rows:
                sx, sy, sz = point[0] - a[0], point[1] - a[1], point[2] - a[2]
                u = sx * h[0] + sy * h[1] + sz * h[2]
                if u < -1e-9 or u > 1 + 1e-9:
                    continue
                v = sx * q[0] + sy * q[1] + sz * q[2]
                distance = sx * normal[0] + sy * normal[1] + sz * normal[2]
                if u < -1e-9 or v < -1e-9 or u + v > 1 + 1e-9 or distance < -1e-9:
                    continue
                if min(u, v, 1 - u - v, abs(distance)) < 1e-9:
                    ambiguous = True
                    break
                hits += 1
            if not ambiguous:
                answers.append(bool(hits % 2))
        if not answers or len(set(answers)) != 1:
            raise ValueError("Ambiguous STL point occupancy")
        return answers[0]


def read_stl(data):
    """Reject malformed, open, degenerate or inconsistently wound binary STL."""
    if len(data) < 84:
        raise ValueError("Truncated binary STL")
    count = struct.unpack_from("<I", data, 80)[0]
    if count == 0 or len(data) != 84 + count * 50:
        raise ValueError("Invalid binary STL triangle count or length")
    triangles, edges, faces = [], Counter(), set()
    volume = 0.0
    for i in range(count):
        values = struct.unpack_from("<12fH", data, 84 + i * 50)
        if not all(math.isfinite(v) for v in values[:12]):
            raise ValueError("Nonfinite STL coordinates or normals")
        a, b, c = (tuple(values[j : j + 3]) for j in (3, 6, 9))
        normal = cross(sub(b, a), sub(c, a))
        if dot(normal, normal) <= 0:
            raise ValueError("Degenerate STL triangle")
        face = tuple(sorted((a, b, c)))
        if face in faces:
            raise ValueError("Duplicate STL triangle")
        faces.add(face)
        for start, end in ((a, b), (b, c), (c, a)):
            edges[start, end] += 1
        volume += dot(a, cross(b, c)) / 6
        triangles.append((a, b, c))
    if any(n != 1 or edges[b, a] != 1 for (a, b), n in edges.items()):
        raise ValueError("STL edges are open, nonmanifold or inconsistently wound")
    if not math.isfinite(volume) or volume <= 0:
        raise ValueError("STL signed volume must be finite and positive")
    return STLMesh(tuple(triangles)), {
        "code": "stl_topology",
        "status": "PASS",
        "message": "Closed paired edges, consistent winding and positive signed volume",
        "triangle_count": count,
        "signed_volume_mm3": volume,
        "scope": (
            "Exact vertex equality; self-intersections and "
            "component nesting not checked"
        ),
    }
