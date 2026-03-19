"""Admin-only router for CIBIL file uploads with background processing.

Upload flow:
  1. POST /upload/files → validates files, saves to temp, creates a
     "processing" UploadHistory record, kicks off a BackgroundTasks worker,
     and returns the upload_id immediately.
  2. GET /upload/status/{upload_id} → returns current progress and status
     so the frontend can render a progress bar and success/failure notification.
"""

from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.role_checker import admin_only, get_current_user
from app.models.upload_history_model import UploadHistory
from app.models.user_model import User
from app.schemas.upload_schema import (
    UploadAcceptedResponse,
    UploadStatusResponse,
)
from app.services.upload_service import (
    create_upload_record,
    process_upload_background,
)

router = APIRouter(prefix="/upload", tags=["Upload"])


def _validate_txt_files(files: list[UploadFile]) -> None:
    """Ensure all uploaded files have `.txt` extension."""
    for file in files:
        filename = file.filename or ""
        if not filename.lower().endswith(".txt"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{filename}' must be a .txt file",
            )


@router.post(
    "/files",
    response_model=UploadAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload CIBIL data files (async, auto-detected)",
    responses={
        202: {
            "description": "Upload accepted — processing in background",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Upload accepted for processing",
                        "upload_id": 42,
                    }
                }
            },
        },
        400: {"description": "Invalid input files"},
        403: {"description": "Insufficient permissions"},
        422: {"description": "Validation error"},
    },
)
async def upload_files(
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(admin_only)],
    files: list[UploadFile] = File(..., description="One or more CIBIL .txt files (auto-detected by header)"),
) -> UploadAcceptedResponse:
    """Accept CIBIL data files and start processing in background.

    Files are auto-detected by their header row and routed to the
    appropriate table (main_data, identity_data, or inquiry_data).

    Returns immediately with an upload_id that can be polled via
    GET /upload/status/{upload_id} to track progress.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file must be uploaded",
        )

    _validate_txt_files(files)

    upload_id, temp_paths = create_upload_record(
        db,
        files=files,
        uploaded_by_user_id=current_user.id,
    )

    background_tasks.add_task(
        process_upload_background,
        upload_id,
        temp_paths,
    )

    return UploadAcceptedResponse(
        message="Upload accepted for processing",
        upload_id=upload_id,
    )


@router.get(
    "/status/{upload_id}",
    response_model=UploadStatusResponse,
    summary="Poll upload processing progress",
    responses={
        200: {
            "description": "Current upload progress and status",
            "content": {
                "application/json": {
                    "example": {
                        "upload_id": 42,
                        "status": "processing",
                        "progress_current": 25000,
                        "progress_total": 540234,
                        "records_inserted": 24800,
                        "records_failed": 200,
                    }
                }
            },
        },
        404: {"description": "Upload not found"},
    },
)
def get_upload_status(
    upload_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UploadStatusResponse:
    """Return the current progress and status of an upload.

    The frontend should poll this endpoint (e.g. every 2-3 seconds) while
    status is "processing" to update the progress bar.  Once status changes
    to "success", "partial", or "failed", processing is complete.
    """
    history = db.get(UploadHistory, upload_id)
    if not history:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload {upload_id} not found",
        )

    return UploadStatusResponse(
        upload_id=history.id,
        status=history.status,
        progress_current=history.progress_current,
        progress_total=history.progress_total,
        records_inserted=history.records_inserted,
        records_failed=history.records_failed,
    )


@router.get("/test", response_class=HTMLResponse, include_in_schema=False)
def upload_test_page():
    """Lightweight upload test page with multi-file picker."""
    return """<!DOCTYPE html>
<html><head><title>CIBIL Upload Test</title>
<style>
  body { font-family: system-ui; max-width: 600px; margin: 60px auto; padding: 0 20px; }
  h2 { margin-bottom: 4px; }
  p { color: #666; margin-top: 0; }
  label { display: block; font-weight: 600; margin: 20px 0 8px; }
  input[type=text] { width: 100%; padding: 8px; box-sizing: border-box; }
  input[type=file] { margin: 8px 0; }
  button { background: #2563eb; color: #fff; border: none; padding: 10px 24px;
           border-radius: 4px; cursor: pointer; font-size: 14px; margin-top: 16px; }
  button:disabled { background: #94a3b8; cursor: not-allowed; }
  #status { margin-top: 20px; padding: 12px; border-radius: 4px; display: none; }
  .ok { background: #dcfce7; color: #166534; display: block !important; }
  .err { background: #fee2e2; color: #991b1b; display: block !important; }
  .info { background: #dbeafe; color: #1e40af; display: block !important; }
  #progress { margin-top: 12px; display: none; }
  #progress.show { display: block; }
  progress { width: 100%; height: 20px; }
</style></head>
<body>
  <h2>CIBIL File Upload</h2>
  <p>Select one or more .txt files. They are auto-detected by header.</p>
  <label>JWT Token</label>
  <input type="text" id="token" placeholder="Paste your Bearer token here">
  <label>Select Files</label>
  <input type="file" id="files" multiple accept=".txt">
  <br>
  <button id="btn" onclick="doUpload()">Upload</button>
  <div id="status"></div>
  <div id="progress">
    <progress id="bar" value="0" max="100"></progress>
    <span id="ptext"></span>
  </div>
<script>
async function doUpload() {
  const token = document.getElementById('token').value.trim();
  const files = document.getElementById('files').files;
  const status = document.getElementById('status');
  const btn = document.getElementById('btn');
  if (!token) { status.className='err'; status.textContent='Token required'; return; }
  if (!files.length) { status.className='err'; status.textContent='Select at least one file'; return; }
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  btn.disabled = true;
  status.className='info'; status.textContent='Uploading...';
  try {
    const r = await fetch('/upload/files', {
      method: 'POST', body: fd,
      headers: { 'Authorization': 'Bearer ' + token }
    });
    const data = await r.json();
    if (!r.ok) { status.className='err'; status.textContent=JSON.stringify(data); btn.disabled=false; return; }
    status.className='ok'; status.textContent='Upload accepted (ID: '+data.upload_id+'). Polling...';
    pollStatus(data.upload_id, token);
  } catch(e) { status.className='err'; status.textContent=e.message; btn.disabled=false; }
}
async function pollStatus(id, token) {
  const status = document.getElementById('status');
  const prog = document.getElementById('progress');
  const bar = document.getElementById('bar');
  const ptext = document.getElementById('ptext');
  prog.className = 'show';
  const poll = setInterval(async () => {
    try {
      const r = await fetch('/upload/status/'+id, {
        headers: { 'Authorization': 'Bearer ' + token }
      });
      const d = await r.json();
      const pct = d.progress_total ? Math.round(d.progress_current/d.progress_total*100) : 0;
      bar.value = pct; ptext.textContent = pct+'% ('+d.records_inserted+' inserted, '+d.records_failed+' failed)';
      if (d.status !== 'processing') {
        clearInterval(poll);
        bar.value = 100;
        status.className = d.status === 'success' ? 'ok' : d.status === 'partial' ? 'info' : 'err';
        status.textContent = 'Done: ' + d.status + ' | Inserted: '+d.records_inserted+' | Failed: '+d.records_failed;
        document.getElementById('btn').disabled = false;
      }
    } catch(e) { clearInterval(poll); status.className='err'; status.textContent=e.message; }
  }, 2000);
}
</script></body></html>"""
