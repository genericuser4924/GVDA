"""Read bounded ZIP station documents without accessing GUI objects."""
import ntpath
import stat
import zipfile
from pathlib import Path, PurePosixPath

from .archive_document import recognize_station_document


class ArchiveLimitError(ValueError):
    """Stop an import when a global resource limit is exceeded."""


def read_station_zip(
    archive_path,
    cancelled=None,
    max_members=1000,
    max_member_bytes=32 * 1024 * 1024,
    max_total_bytes=128 * 1024 * 1024,
):
    """Return candidate documents and individual refusal reasons."""
    check = cancelled or (lambda: False)
    path = Path(archive_path).resolve()

    def checkpoint():
        if check():
            raise InterruptedError("Archive reading cancelled.")

    checkpoint()
    initial = path.stat()
    initial_signature = (initial.st_size, initial.st_mtime_ns)

    candidates = []
    refused = []
    total_bytes = 0

    with zipfile.ZipFile(path, "r") as archive:
        members = archive.infolist()

        if len(members) > max_members:
            raise ArchiveLimitError(
                f"The archive exceeds the {max_members} member limit."
            )

        for member_index, info in enumerate(members):
            checkpoint()

            if info.is_dir():
                continue

            member_path = info.filename
            normalized = member_path.replace("\\", "/")
            relative = PurePosixPath(normalized)
            station_id = ntpath.splitext(
                ntpath.basename(normalized)
            )[0]

            identity = {
                "member_index": member_index,
                "member_path": member_path,
                "station_id": station_id,
            }

            def refuse(reason):
                refused.append({
                    **identity,
                    "status": "refused",
                    "reason": reason,
                })

            # Accept regular members only; never extract archive paths.
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)

            if (
                relative.is_absolute()
                or ".." in relative.parts
                or ntpath.splitdrive(normalized)[0]
            ):
                refuse("Unsafe archive member path.")
                continue

            if file_type not in (0, stat.S_IFREG):
                refuse("Links and special files are not supported.")
                continue

            if (
                "__MACOSX" in relative.parts
                or relative.name.startswith(".")
            ):
                refuse("Hidden or auxiliary file.")
                continue

            if info.flag_bits & 1:
                refuse("Encrypted members are not supported.")
                continue

            if not station_id:
                refuse("The member has no usable station identifier.")
                continue

            if info.file_size > max_member_bytes:
                refuse("The member exceeds the uncompressed size limit.")
                continue

            try:
                payload = bytearray()

                with archive.open(info, "r") as stream:
                    while True:
                        checkpoint()
                        block = stream.read(64 * 1024)

                        if not block:
                            break

                        total_bytes += len(block)

                        if total_bytes > max_total_bytes:
                            raise ArchiveLimitError(
                                "The archive exceeds the total "
                                "uncompressed reading limit."
                            )

                        if len(payload) + len(block) > max_member_bytes:
                            raise ValueError(
                                "The member exceeds the actual reading limit."
                            )

                        payload.extend(block)

                # Reject common nested archive signatures before text parsing.
                if (
                    payload[:4] in (b"PK\x03\x04", b"PK\x05\x06")
                    or payload[:6] == b"7z\xbc\xaf\x27\x1c"
                    or payload[:4] == b"Rar!"
                    or payload[:2] == b"\x1f\x8b"
                ):
                    raise ValueError(
                        "Nested compressed documents are not supported."
                    )

                document = recognize_station_document(
                    member_path,
                    bytes(payload),
                    cancelled=check,
                )
                document.update(identity)
                candidates.append(document)

            except (InterruptedError, ArchiveLimitError):
                raise
            except (
                ValueError,
                UnicodeError,
                RuntimeError,
                NotImplementedError,
                zipfile.BadZipFile,
                EOFError,
                OSError,
            ) as error:
                refuse(f"{type(error).__name__}: {error}")

    checkpoint()
    final = path.stat()

    if (final.st_size, final.st_mtime_ns) != initial_signature:
        raise ValueError(
            "The archive changed during reading. Please load it again."
        )

    return {
        "archive_path": str(path),
        "archive_signature": initial_signature,
        "candidates": candidates,
        "refused": refused,
        "total_read_bytes": total_bytes,
    }