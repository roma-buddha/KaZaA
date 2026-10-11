"""Selective BitTorrent inspection/download using the isolated worker contract."""
from pathlib import Path
import tempfile
import time
from urllib.request import Request, urlopen

from .sources import local_torrent_path, output_paths, validate_selection

METADATA_TIMEOUT = 180
MAX_METADATA = 16 * 1024 * 1024


def engine():
    try:
        import libtorrent as lt
    except ImportError as exc:
        raise ValueError("Torrent support needs libtorrent. Install the app's requirements-video.txt runtime.") from exc
    return lt


def session(lt, request):
    settings = {"listen_interfaces": "0.0.0.0:0", "enable_dht": True, "enable_lsd": True,
                "enable_upnp": False, "enable_natpmp": False, "announce_to_all_trackers": True,
                "announce_to_all_tiers": True, "user_agent": "KaZaA/2.0",
                "alert_mask": lt.alert.category_t.status_notification | lt.alert.category_t.storage_notification | lt.alert.category_t.error_notification}
    settings.update(request.get("session_settings", {}))
    return lt.session(settings)


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        file.write(data)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def hashes(ti):
    value = ti.info_hashes()
    return (["v1:" + str(value.v1)] if value.has_v1() else []) + (["v2:" + str(value.v2)] if value.has_v2() else [])


def manifest(lt, ti):
    files = ti.files()
    if any(files.file_flags(i) & lt.file_storage.flag_symlink for i in range(files.num_files())):
        raise ValueError("Torrent symbolic links are not supported.")
    return [{"index": i, "path": files.file_path(i).replace("\\", "/"), "size": files.file_size(i),
             "pad": bool(files.file_flags(i) & lt.file_storage.flag_pad_file)} for i in range(files.num_files())]


def save_resume(lt, ses, handle, path, timeout=5):
    handle.save_resume_data(lt.save_resume_flags_t.save_info_dict | lt.save_resume_flags_t.flush_disk_cache)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for alert in ses.pop_alerts():
            if isinstance(alert, lt.save_resume_data_alert):
                atomic_write(path, bytes(lt.write_resume_data_buf(alert.params)))
                return
            if isinstance(alert, lt.save_resume_data_failed_alert):
                raise OSError("Could not save torrent resume data: " + alert.error.message())
        time.sleep(0.05)
    raise OSError("Timed out saving torrent resume data; existing files were kept.")


def pause_and_flush(lt, ses, handle, timeout=5):
    # Resume-data alerts alone can precede the last Windows disk writes.
    ses.pop_alerts()
    handle.pause()
    handle.flush_cache()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(isinstance(alert, lt.cache_flushed_alert) for alert in ses.pop_alerts()):
            return
        time.sleep(0.05)
    raise OSError("Timed out flushing torrent files; existing data was kept.")


def torrent_health(status):
    seeds = max(0, status.num_seeds)
    peers = max(0, status.num_peers - seeds)
    return {"seeds": seeds, "peers": peers, "reported_seeds": status.num_complete,
            "reported_peers": status.num_incomplete,
            "active": bool(status.num_peers or status.download_payload_rate), "observed": time.time()}


def inspect_torrent(request, stop):
    lt = engine()
    url = request["url"]
    cache = Path(request["cache_dir"])
    ses = handle = None
    try:
        if url.lower().startswith("magnet:"):
            ses = session(lt, request)
            params = lt.parse_magnet_uri(url)
            params.save_path = str(cache / "inspection")
            params.flags &= ~(lt.torrent_flags.paused | lt.torrent_flags.auto_managed)
            params.flags |= lt.torrent_flags.default_dont_download | lt.torrent_flags.upload_mode
            handle = ses.add_torrent(params)
            for peer in request.get("peers", []):
                handle.connect_peer(tuple(peer))
            deadline = time.monotonic() + request.get("metadata_timeout", METADATA_TIMEOUT)
            while not handle.status().has_metadata:
                if stop.is_set():
                    raise ValueError("Cancelled")
                status = handle.status()
                if status.errc.value():
                    raise ValueError(status.errc.message())
                if time.monotonic() >= deadline:
                    raise ValueError("No peers supplied metadata for this magnet. Try inspecting it again later.")
                time.sleep(0.1)
            handle.pause()
            ti = handle.torrent_file()
        else:
            if url.lower().startswith(("http://", "https://")):
                with urlopen(Request(url, headers={"User-Agent": "KaZaA/2.0"}), timeout=30) as response:
                    raw = response.read(MAX_METADATA + 1)
            else:
                with local_torrent_path(url).open("rb") as file:
                    raw = file.read(MAX_METADATA + 1)
            if len(raw) > MAX_METADATA:
                raise ValueError("This torrent metadata file is too large.")
            ti = lt.torrent_info(lt.bdecode(raw))
        if stop.is_set():
            raise ValueError("Cancelled")
        entries = manifest(lt, ti)
        output_paths(entries, cache / "inspection")
        identity = hashes(ti)
        metadata_file = cache / (identity[0].replace(":", "-") + ".metadata")
        if handle:
            save_resume(lt, ses, handle, metadata_file)
        else:
            params = lt.add_torrent_params()
            params.ti = ti
            atomic_write(metadata_file, bytes(lt.write_resume_data_buf(params)))
        return {"url": url, "source": "torrent", "title": ti.name(), "hashes": identity,
                "manifest": entries, "size": sum(f["size"] for f in entries if not f["pad"]),
                "metadata_file": str(metadata_file)}
    finally:
        if handle is not None:
            ses.remove_torrent(handle)


def download_torrent(request, emit, stop):
    if stop.is_set():
        raise ValueError("Cancelled")
    lt = engine()
    torrent, options = request["torrent"], request["options"]
    entries = torrent["manifest"]
    selected = validate_selection(entries, options["selected_files"])
    paths = output_paths(entries, options["folder"])
    metadata = lt.read_resume_data(Path(torrent["metadata_file"]).read_bytes())
    params = metadata
    resume_file = Path(torrent["resume_file"])
    if resume_file.is_file():
        try:
            restored = lt.read_resume_data(resume_file.read_bytes())
            if restored.ti is not None and set(hashes(restored.ti)) & set(torrent["hashes"]):
                params = restored
        except Exception:
            pass  # Recheck existing pieces when the resume file cannot be read.
    if params.ti is None or not set(hashes(params.ti)) & set(torrent["hashes"]):
        raise ValueError("Torrent metadata does not match this download.")
    params.save_path = str(Path(options["folder"]).resolve())
    Path(params.save_path).mkdir(parents=True, exist_ok=True)
    params.file_priorities = [4 if i in selected else 0 for i in range(len(entries))]
    params.piece_priorities = []
    params.renamed_files = {}
    params.flags &= ~(lt.torrent_flags.auto_managed | lt.torrent_flags.upload_mode | lt.torrent_flags.stop_when_ready | lt.torrent_flags.seed_mode)
    params.flags |= lt.torrent_flags.paused | lt.torrent_flags.sequential_download
    ses = session(lt, request)
    handle = ses.add_torrent(params)
    total = sum(item["size"] for item in entries if item["index"] in selected)
    allowed = set(paths.values())
    previous_files = [path for path in request.get("owned_files", []) if path in allowed and Path(path).is_file()]
    try:
        handle.resume()
        for peer in request.get("peers", []):
            handle.connect_peer(tuple(peer))
        last_emit = last_save = 0
        while True:
            status = handle.status()
            if status.errc.value():
                raise ValueError("Torrent error: " + status.errc.message())
            existing = list(dict.fromkeys(previous_files + [paths[i] for i in selected if Path(paths[i]).is_file()]))
            if stop.is_set():
                pause_and_flush(lt, ses, handle)
                save_resume(lt, ses, handle, resume_file)
                emit("progress", {"files": existing})
                raise ValueError("Cancelled")
            now = time.monotonic()
            checking = status.state in (lt.torrent_status.checking_files, lt.torrent_status.checking_resume_data)
            if now - last_emit >= 0.5:
                done = min(total, status.total_wanted_done)
                rate = status.download_payload_rate
                emit("progress", {"status": "starting" if checking else "downloading", "percent": None if checking else (done * 100 / total if total else 100),
                                  "downloaded_bytes": done, "total_bytes": total, "speed": rate,
                                  "eta": (total - done) / rate if rate else None, "files": existing,
                                  "torrent_health": torrent_health(status)})
                last_emit = now
            # A full seed forgets file priorities, so total_wanted can include
            # deselected files already on disk. Verify our selected files directly.
            file_progress = handle.file_progress() if status.is_finished and not checking else None
            if file_progress is not None and all(
                file_progress[item["index"]] >= item["size"]
                for item in entries if item["index"] in selected
            ):
                pause_and_flush(lt, ses, handle)
                save_resume(lt, ses, handle, resume_file)
                if not all(Path(paths[i]).is_file() for i in selected):
                    raise ValueError("The selected torrent files could not be finalized.")
                return {"files": existing, "size": total, "total_bytes": total, "downloaded_bytes": total}
            if now - last_save >= 10:
                save_resume(lt, ses, handle, resume_file)
                last_save = now
            time.sleep(0.1)
    finally:
        handle.pause()
        ses.remove_torrent(handle)
