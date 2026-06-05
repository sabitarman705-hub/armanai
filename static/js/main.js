/* ── Тек Restore беті үшін ────────────────────────────────────────────────── */

// Dropped файлды сақтаймыз (input.files DnD-де жаңармайды)
let _droppedRestoreFile = null;

// Браузер бетін ашпасын
document.addEventListener('dragover', e => e.preventDefault());
document.addEventListener('drop',     e => e.preventDefault());

// Ctrl+V / Command+V — алмасу буферінен сурет paste жасау
document.addEventListener('paste', e => {
  const items = e.clipboardData?.items || [];
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile();
      if (!file) continue;
      // Қай бетте екенімізге қарай paste жасаймыз
      if (document.getElementById('restoreDropZone')) {
        _droppedRestoreFile = file;
        showRestorePreview(file,
          document.getElementById('restorePreview'),
          document.getElementById('restoreDropContent'));
        showToast('Сурет paste жасалды', 'success');
      }
      break;
    }
  }
});

function initDropRestore(zoneId, inputId, previewId, contentId) {
  const zone    = document.getElementById(zoneId);
  const input   = document.getElementById(inputId);
  const preview = document.getElementById(previewId);
  const content = document.getElementById(contentId);
  if (!zone || !input) return;

  zone.addEventListener('click', () => input.click());
  zone.addEventListener('dragover', e => {
    e.preventDefault(); e.stopPropagation();
    zone.classList.add('drag-over');
  });
  zone.addEventListener('dragleave', e => {
    if (!zone.contains(e.relatedTarget)) zone.classList.remove('drag-over');
  });
  zone.addEventListener('drop', e => {
    e.preventDefault(); e.stopPropagation();
    zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('image/')) {
      _droppedRestoreFile = file;
      showRestorePreview(file, preview, content);
    }
  });
  input.addEventListener('change', () => {
    if (input.files[0]) {
      _droppedRestoreFile = null;
      showRestorePreview(input.files[0], preview, content);
    }
  });
}

function showRestorePreview(file, preview, content) {
  const reader = new FileReader();
  reader.onload = e => {
    preview.src = e.target.result;
    preview.classList.remove('hidden');
    if (content) content.classList.add('hidden');
  };
  reader.readAsDataURL(file);
}

if (document.getElementById('restoreDropZone')) {
  initDropRestore('restoreDropZone', 'restoreFile', 'restorePreview', 'restoreDropContent');
}

async function startRestore() {
  const fileInput  = document.getElementById('restoreFile');
  const photoFile  = _droppedRestoreFile || fileInput.files[0];
  const model      = document.getElementById('restoreModel').value;
  const btn        = document.getElementById('restoreBtn');
  const progress   = document.getElementById('restoreProgress');
  const statusEl   = document.getElementById('restoreStatus');
  const errorEl    = document.getElementById('restoreError');
  const origImg    = document.getElementById('origImg');
  const resultImg  = document.getElementById('resultImg');
  const dlBtn      = document.getElementById('downloadRestore');

  if (!photoFile) { showRestoreError(errorEl, 'Алдымен сурет жүктеңіз'); return; }

  btn.disabled = true;
  progress.classList.remove('hidden');
  errorEl.classList.add('hidden');
  dlBtn.classList.add('hidden');

  const steps = ['Сурет жіберілуде…','AI өңдеуде…','Нәтиже дайындалуда…','Аяқталуға жақын…'];
  let si = 0;
  const ticker = setInterval(() => { statusEl.textContent = steps[si++ % steps.length]; }, 8000);

  const fd = new FormData();
  fd.append('photo', photoFile);
  fd.append('model', model);

  try {
    const res  = await fetch('/api/restore', { method: 'POST', body: fd });
    const data = await res.json();
    clearInterval(ticker);
    if (data.error) { showRestoreError(errorEl, data.error); return; }

    origImg.src = data.original || URL.createObjectURL(fileInput.files[0]);
    origImg.classList.remove('placeholder-img');
    resultImg.src = data.result;
    resultImg.classList.remove('placeholder-img');
    dlBtn.href = data.result;
    dlBtn.classList.remove('hidden');
    progress.classList.add('hidden');

    // Тарихқа қосу (сурет жүктелгенде)
    resultImg.onload = () => {
      const sel      = document.getElementById('restoreModel');
      const modeName = sel ? sel.options[sel.selectedIndex].text : model;
      addRestoreHistory(data.original || '', data.result, modeName);
    };
  } catch (e) {
    clearInterval(ticker);
    showRestoreError(errorEl, 'Байланыс қатесі: ' + e.message);
  } finally {
    btn.disabled = false;
    progress.classList.add('hidden');
  }
}

// ── Restore History ──────────────────────────────────────────────────────────

function getRestoreThumb(imgEl) {
  if (!imgEl || !imgEl.naturalWidth) return '';
  try {
    const maxSize = 90;
    const ratio   = Math.min(maxSize / imgEl.naturalWidth, maxSize / imgEl.naturalHeight, 1);
    const w = Math.round(imgEl.naturalWidth * ratio);
    const h = Math.round(imgEl.naturalHeight * ratio);
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    c.getContext('2d').drawImage(imgEl, 0, 0, w, h);
    return c.toDataURL('image/jpeg', 0.65);
  } catch (_) { return ''; }
}

function addRestoreHistory(origUrl, resultUrl, modeName) {
  const origThumb   = getRestoreThumb(document.getElementById('origImg'));
  const resultThumb = getRestoreThumb(document.getElementById('resultImg'));
  const hist = JSON.parse(localStorage.getItem('restoreHistory') || '[]');
  hist.unshift({ origUrl, resultUrl, origThumb, resultThumb, modeName, ts: Date.now() });
  if (hist.length > 20) hist.splice(20);
  try { localStorage.setItem('restoreHistory', JSON.stringify(hist)); } catch (_) {}
  renderRestoreHistory();
}

function renderRestoreHistory() {
  const section = document.getElementById('restoreHistorySection');
  const list    = document.getElementById('restoreHistoryList');
  if (!section || !list) return;
  const hist = JSON.parse(localStorage.getItem('restoreHistory') || '[]');
  if (!hist.length) { section.classList.add('hidden'); return; }
  section.classList.remove('hidden');
  list.innerHTML = hist.map((item, i) => {
    const d    = new Date(item.ts);
    const dStr = d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
               + ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    const oImg = item.origThumb
      ? `<img src="${item.origThumb}" class="h-photo" alt=""/>`
      : `<div class="h-photo h-photo-empty">🖼</div>`;
    const rImg = item.resultThumb
      ? `<img src="${item.resultThumb}" class="h-photo" alt=""/>`
      : `<div class="h-photo h-photo-empty">✨</div>`;
    return `<div class="history-item" onclick="viewRestoreResult(${i})">
      <div class="h-photos">${oImg}<span class="h-arr">→</span>${rImg}</div>
      <div class="h-body">
        <div class="h-top-row"><span class="history-model">${item.modeName || 'Өңдеу'}</span></div>
        <span class="history-date">${dStr}</span>
      </div>
      <a href="${item.resultUrl}" download="restored_${i+1}.jpg" class="history-dl"
         onclick="event.stopPropagation()" title="Жүктеу">⬇</a>
    </div>`;
  }).join('');
}

let _restoreHistory = [];
function viewRestoreResult(i) {
  _restoreHistory = JSON.parse(localStorage.getItem('restoreHistory') || '[]');
  const item = _restoreHistory[i];
  if (!item) return;
  const oEl  = document.getElementById('origImg');
  const rEl  = document.getElementById('resultImg');
  const dlEl = document.getElementById('downloadRestore');
  if (oEl)  { oEl.src  = item.origUrl;   oEl.classList.remove('placeholder-img'); }
  if (rEl)  { rEl.src  = item.resultUrl; rEl.classList.remove('placeholder-img'); }
  if (dlEl) { dlEl.href = item.resultUrl; dlEl.classList.remove('hidden'); }
  document.getElementById('compareWrap')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function clearRestoreHistory() {
  localStorage.removeItem('restoreHistory');
  renderRestoreHistory();
}

if (document.getElementById('restoreHistorySection')) renderRestoreHistory();

function showRestoreError(el, msg) {
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
  document.getElementById('restoreProgress')?.classList.add('hidden');
  const btn = document.getElementById('restoreBtn');
  if (btn) btn.disabled = false;
}
