from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import activity_log, backups, cfg_editor, docker_control, mods_editor
from app.instances import get_instance
from app.templating import templates

router = APIRouter()


def _get_instance_or_404(name: str):
    instance = get_instance(name)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Instance '{name}' not found")
    return instance


def _split_ids(raw: str) -> list[str]:
    parts = raw.replace(",", "\n").splitlines()
    return [p.strip() for p in parts if p.strip()]


@router.get("/instances/{name}")
def instance_detail(request: Request, name: str):
    instance = _get_instance_or_404(name)
    status = docker_control.get_status(instance.container_name)

    settings = None
    mods = []
    settings_error = None
    if instance.cfg_path.exists():
        try:
            settings = cfg_editor.read_settings(instance.cfg_path, instance.sandbox_config_path)
        except Exception as exc:  # noqa: BLE001 - surface to the page, don't crash it
            settings_error = str(exc)
    else:
        settings_error = f"Config not found at {instance.cfg_path}"

    # Sandbox_config.sbc is the live, continuously-autosaved copy -- prefer it
    # for listing, falling back to Sandbox.sbc only if it doesn't exist yet.
    mods_source = (
        instance.sandbox_config_path if instance.sandbox_config_path.exists() else instance.sandbox_sbc_path
    )
    mods_error = None
    if mods_source.exists():
        try:
            mods = mods_editor.list_mods(mods_source)
        except Exception as exc:  # noqa: BLE001
            mods_error = str(exc)
    else:
        mods_error = f"World save not found at {mods_source}"

    activity = []
    activity_error = None
    if status == "running":
        try:
            activity = activity_log.recent_activity(instance.container_name, tail=100)
        except Exception as exc:  # noqa: BLE001
            activity_error = str(exc)

    backup_list = backups.list_backups(instance)

    return templates.TemplateResponse(
        request,
        "instance_detail.html",
        {
            "instance": instance,
            "status": status,
            "settings": settings,
            "settings_error": settings_error,
            "mods": mods,
            "mods_error": mods_error,
            "activity": activity,
            "activity_error": activity_error,
            "backups": backup_list,
        },
    )


@router.post("/instances/{name}/start")
def start_instance(name: str):
    instance = _get_instance_or_404(name)
    docker_control.start(instance.container_name)
    return RedirectResponse(f"/instances/{name}", status_code=303)


@router.post("/instances/{name}/stop")
def stop_instance(name: str):
    instance = _get_instance_or_404(name)
    docker_control.stop(instance.container_name)
    return RedirectResponse(f"/instances/{name}", status_code=303)


@router.post("/instances/{name}/restart")
def restart_instance(name: str):
    instance = _get_instance_or_404(name)
    docker_control.restart(instance.container_name)
    return RedirectResponse(f"/instances/{name}", status_code=303)


@router.post("/instances/{name}/settings")
def update_settings(
    name: str,
    game_mode: str = Form(...),
    total_pcu: int = Form(...),
    pirate_pcu: int = Form(...),
    max_players: int = Form(...),
    max_backup_saves: int = Form(...),
    server_name: str = Form(...),
    administrators: str = Form(""),
    banned: str = Form(""),
    reserved: str = Form(""),
):
    instance = _get_instance_or_404(name)
    current = cfg_editor.read_settings(instance.cfg_path, instance.sandbox_config_path)
    current.game_mode = game_mode
    current.total_pcu = total_pcu
    current.pirate_pcu = pirate_pcu
    current.max_players = max_players
    current.max_backup_saves = max_backup_saves
    current.server_name = server_name
    current.administrators = _split_ids(administrators)
    current.banned = _split_ids(banned)
    current.reserved = _split_ids(reserved)
    cfg_editor.write_settings(instance.cfg_path, instance.sandbox_config_path, current)
    return RedirectResponse(f"/instances/{name}", status_code=303)


@router.post("/instances/{name}/password/clear")
def clear_password(name: str):
    instance = _get_instance_or_404(name)
    cfg_editor.clear_password(instance.cfg_path)
    return RedirectResponse(f"/instances/{name}", status_code=303)


@router.post("/instances/{name}/password/set")
def set_password(name: str, password: str = Form(...)):
    instance = _get_instance_or_404(name)
    cfg_editor.set_password(instance.cfg_path, password)
    return RedirectResponse(f"/instances/{name}", status_code=303)


def _mod_file_paths(instance):
    """Both files carry a <Mods> block; keep them in sync (see mods_editor docstring)."""
    return [p for p in (instance.sandbox_sbc_path, instance.sandbox_config_path) if p.exists()]


@router.post("/instances/{name}/mods/add")
def add_mod(name: str, published_file_id: str = Form(...), friendly_name: str = Form("")):
    instance = _get_instance_or_404(name)
    for path in _mod_file_paths(instance):
        mods_editor.add_mod(path, published_file_id.strip(), friendly_name.strip())
    return RedirectResponse(f"/instances/{name}", status_code=303)


@router.post("/instances/{name}/mods/{published_file_id}/remove")
def remove_mod(name: str, published_file_id: str):
    instance = _get_instance_or_404(name)
    for path in _mod_file_paths(instance):
        try:
            mods_editor.remove_mod(path, published_file_id)
        except mods_editor.ModNotFoundError:
            pass  # fine if only one of the two files currently has it
    return RedirectResponse(f"/instances/{name}", status_code=303)


@router.post("/instances/{name}/backups/{backup_name}/restore")
def restore_backup(name: str, backup_name: str):
    instance = _get_instance_or_404(name)
    backups.restore_backup(instance, backup_name)
    return RedirectResponse(f"/instances/{name}", status_code=303)
