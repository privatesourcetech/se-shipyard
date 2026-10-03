from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import docker_control, instances
from app.instances import Instance
from app.templating import templates

router = APIRouter()


@router.get("/")
def dashboard(request: Request):
    rows = []
    for instance in instances.load_instances():
        rows.append(
            {
                "instance": instance,
                "status": docker_control.get_status(instance.container_name),
            }
        )
    return templates.TemplateResponse(
        request, "dashboard.html", {"rows": rows}
    )


@router.post("/instances")
def create_instance(
    name: str = Form(...),
    container_name: str = Form(...),
    dataset_mount: str = Form(...),
    instance_dir: str = Form(...),
    world_folder: str = Form(...),
    backup_mount: str = Form(...),
):
    instances.add_instance(
        Instance(
            name=name,
            container_name=container_name,
            dataset_mount=dataset_mount,
            instance_dir=instance_dir,
            world_folder=world_folder,
            backup_mount=backup_mount,
        )
    )
    return RedirectResponse("/", status_code=303)


@router.post("/instances/{name}/delete")
def delete_instance(name: str):
    instances.remove_instance(name)
    return RedirectResponse("/", status_code=303)
