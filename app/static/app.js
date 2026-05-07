// ── Estado global ─────────────────────────────────────────────────────
let uploadedPdfs = [];


// ════════════════════════════════════════════════════════════════════
// ALERTA PERSONALIZADO
// ════════════════════════════════════════════════════════════════════

function showAlert(message, onConfirm) {
    const overlay    = document.getElementById('alertOverlay');
    const msgEl      = document.getElementById('alertMessage');
    const btnConfirm = document.getElementById('alertConfirm');
    const btnCancel  = document.getElementById('alertCancel');

    msgEl.textContent = message;
    overlay.classList.remove('hidden');

    const newConfirm = btnConfirm.cloneNode(true);
    const newCancel  = btnCancel.cloneNode(true);
    btnConfirm.replaceWith(newConfirm);
    btnCancel.replaceWith(newCancel);

    document.getElementById('alertConfirm').addEventListener('click', () => {
        overlay.classList.add('hidden');
        onConfirm();
    });

    document.getElementById('alertCancel').addEventListener('click', () => {
        overlay.classList.add('hidden');
    });
}

document.getElementById('alertOverlay').addEventListener('click', function(e) {
    if (e.target === this) this.classList.add('hidden');
});


// ════════════════════════════════════════════════════════════════════
// MENSAGEM DE FEEDBACK
// ════════════════════════════════════════════════════════════════════

function showMsg(text, type) {
    const msgEl     = document.getElementById('uploadMsg');
    msgEl.className = `msg ${type}`;
    msgEl.textContent = text;
}


// ════════════════════════════════════════════════════════════════════
// LISTA DE PDFs
// ════════════════════════════════════════════════════════════════════

async function loadPdfList() {
    try {
        const resp   = await fetch('/pdfs');
        const json   = await resp.json();
        uploadedPdfs = json.pdfs || [];
        renderPdfList();
    } catch (err) {
        console.error('Erro ao carregar lista de PDFs:', err);
    }
}

function renderPdfList() {
    const container = document.getElementById('pdfListContainer');
    const list      = document.getElementById('pdfList');
    const count     = document.getElementById('pdfCount');

    list.innerHTML = '';

    if (!uploadedPdfs.length) {
        container.classList.add('hidden');
        return;
    }

    container.classList.remove('hidden');

    const totalChunks = uploadedPdfs.reduce((acc, p) => acc + (p.chunks || 0), 0);
    const totalImages = uploadedPdfs.reduce((acc, p) => acc + (p.image_chunks || 0), 0);
    count.textContent = (
        `Total: ${uploadedPdfs.length} PDF(s) | ` +
        `${totalChunks} trechos | ` +
        `${totalImages} imagem(ns) indexada(s)`
    );

    uploadedPdfs.forEach(pdf => {
        const topicsHtml = pdf.topics && pdf.topics.length
            ? `<div class="pdf-topics">
                 ${pdf.topics.map(t => `<span class="topic-tag">${t}</span>`).join('')}
               </div>`
            : '';

        const summaryHtml = pdf.summary
            ? `<div class="pdf-summary">${pdf.summary}</div>`
            : '';

        const li = document.createElement('li');
        li.className = 'pdf-item';
        li.innerHTML = `
            <div class="pdf-info">
                <div class="pdf-header">
                    <span class="pdf-icon">📎</span>
                    <strong class="pdf-name">${pdf.filename}</strong>
                    <span class="pdf-meta">
                        ${pdf.text_chunks || 0} texto · ${pdf.image_chunks || 0} img
                    </span>
                </div>
                ${summaryHtml}
                ${topicsHtml}
            </div>
            <button
                class="btn-delete"
                data-id="${pdf.file_id}"
                data-name="${pdf.filename}"
                title="Remover este PDF do banco"
            >
                🗑️
            </button>
        `;
        list.appendChild(li);
    });

    list.querySelectorAll('.btn-delete').forEach(btn => {
        btn.addEventListener('click', () => {
            deletePdf(btn.dataset.id, btn.dataset.name);
        });
    });
}


// ════════════════════════════════════════════════════════════════════
// UPLOAD COM POLLING DE STATUS
// ════════════════════════════════════════════════════════════════════

document.getElementById('uploadForm').addEventListener('submit', async function(e) {
    e.preventDefault();

    const fileInput = document.getElementById('fileInput');
    const uploadBtn = document.getElementById('uploadBtn');

    if (!fileInput.files.length) {
        showMsg('Selecione um arquivo PDF.', 'error');
        return;
    }

    showMsg('📥 Enviando arquivo...', 'info');
    uploadBtn.disabled = true;

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    try {
        const resp = await fetch('/upload', { method: 'POST', body: formData });
        const json = await resp.json();

        if (!resp.ok) {
            showMsg(json.detail || 'Erro ao enviar PDF.', 'error');
            uploadBtn.disabled = false;
            return;
        }

        fileInput.value = '';
        await pollUploadStatus(json.file_id, json.filename);

    } catch (err) {
        showMsg('Erro de conexão ao enviar o arquivo.', 'error');
    } finally {
        uploadBtn.disabled = false;
    }
});


async function pollUploadStatus(fileId, filename) {
    const INTERVAL   = 3000;
    const WARN_AFTER = 120;

    let tries = 0;

    return new Promise((resolve) => {
        const interval = setInterval(async () => {
            tries++;

            const segundos  = Math.floor((tries * INTERVAL) / 1000);
            const minutos   = Math.floor(segundos / 60);
            const segsResto = segundos % 60;
            const tempo     = minutos > 0
                ? `${minutos}min ${segsResto}s`
                : `${segsResto}s`;

            try {
                const resp = await fetch(`/upload-status/${fileId}`);

                if (resp.status === 404) {
                    showMsg(`⏳ Aguardando início do processamento... (${tempo})`, 'info');
                    return;
                }

                const json = await resp.json();

                // ✅ Concluído
                if (json.status === 'concluido') {
                    clearInterval(interval);
                    showMsg(json.message, 'success');
                    uploadedPdfs.push({
                        file_id:      json.file_id,
                        filename:     json.filename,
                        chunks:       json.chunks,
                        text_chunks:  json.text_chunks,
                        image_chunks: json.image_chunks,
                        summary:      json.summary  || '',
                        topics:       json.topics   || [],
                    });
                    renderPdfList();
                    resolve();
                    return;
                }

                // ❌ Erro no servidor
                if (json.status === 'erro') {
                    clearInterval(interval);
                    showMsg(json.message, 'error');
                    resolve();
                    return;
                }

                // ⏳ Ainda processando
                if (tries === WARN_AFTER) {
                    showMsg(
                        `⏳ ${json.message} (${tempo}) — PDF grande, aguarde...`,
                        'info'
                    );
                    return;
                }

                showMsg(`⏳ ${json.message} (${tempo})`, 'info');

            } catch (err) {
                if (tries >= WARN_AFTER + 20) {
                    clearInterval(interval);
                    showMsg('Erro de conexão. Recarregue a página para verificar.', 'error');
                    resolve();
                }
            }
        }, INTERVAL);
    });
}


// ════════════════════════════════════════════════════════════════════
// EXCLUIR PDF INDIVIDUAL
// ════════════════════════════════════════════════════════════════════

function deletePdf(fileId, filename) {
    showAlert(
        `Deseja remover "${filename}" e todos os seus dados do banco?`,
        async () => {
            try {
                const resp = await fetch(`/delete-pdf/${fileId}`, { method: 'DELETE' });
                const json = await resp.json();

                if (resp.ok) {
                    uploadedPdfs = uploadedPdfs.filter(p => p.file_id !== fileId);
                    renderPdfList();
                    showMsg(json.message, 'success');
                } else {
                    showMsg(json.detail || 'Erro ao remover PDF.', 'error');
                }
            } catch (err) {
                showMsg('Erro de conexão ao remover PDF.', 'error');
            }
        }
    );
}


// ════════════════════════════════════════════════════════════════════
// LIMPAR TUDO
// ════════════════════════════════════════════════════════════════════

document.getElementById('clearAllBtn').addEventListener('click', function() {
    showAlert(
        'Deseja limpar TODO o banco? Todos os dados indexados serão removidos permanentemente.',
        async () => {
            try {
                const resp = await fetch('/clear-all', { method: 'DELETE' });
                const json = await resp.json();

                if (resp.ok) {
                    uploadedPdfs = [];
                    renderPdfList();
                    document.getElementById('searchResults').innerHTML = '';
                    showMsg(json.message, 'success');
                } else {
                    showMsg(json.detail || 'Erro ao limpar banco.', 'error');
                }
            } catch (err) {
                showMsg('Erro de conexão ao limpar banco.', 'error');
            }
        }
    );
});


// ════════════════════════════════════════════════════════════════════
// BUSCA
// ════════════════════════════════════════════════════════════════════

document.getElementById('searchForm').addEventListener('submit', async function(e) {
    e.preventDefault();

    const query     = document.getElementById('queryInput').value.trim();
    const topK      = document.getElementById('topKInput').value;
    const container = document.getElementById('searchResults');

    if (!query) {
        container.innerHTML = '<div class="msg error">Digite uma pergunta.</div>';
        return;
    }

    if (!uploadedPdfs.length) {
        container.innerHTML = '<div class="msg error">Envie ao menos um PDF antes de consultar.</div>';
        return;
    }

    container.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            Consultando IA em todos os PDFs indexados...
        </div>
    `;

    const formData = new FormData();
    formData.append('query', query);
    formData.append('top_k', topK);

    try {
        const resp = await fetch('/search', { method: 'POST', body: formData });
        const json = await resp.json();

        container.innerHTML = '';
        const answerDiv     = document.createElement('div');
        answerDiv.className = 'result-item';
        answerDiv.innerHTML = `<p class="text">${json.answer || 'Sem resposta.'}</p>`;
        container.appendChild(answerDiv);

    } catch (err) {
        container.innerHTML = '<div class="msg error">Erro ao consultar. Tente novamente.</div>';
    }
});


// ── Inicializa ────────────────────────────────────────────────────────
loadPdfList();