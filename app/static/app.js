// ════════════════════════════════════════════════════════════════════
// i18n
// ════════════════════════════════════════════════════════════════════

const LANG_KEY = "selectedLang";
let currentTranslations = {};
let langLabels          = {};


async function fetchLangLabels() {
    try {
        const resp = await fetch("/static/i18n/_labels.json");
        if (resp.ok) langLabels = await resp.json();
    } catch (err) {
        console.error("[i18n] Erro ao carregar _labels.json:", err);
    }
}

function getLangLabel(code) {
    return langLabels[code] || code.toUpperCase();
}

async function loadTranslations(lang) {
    try {
        const resp = await fetch(`/static/i18n/${lang}.json`);
        if (!resp.ok) throw new Error(`Falha ao carregar ${lang}.json`);
        currentTranslations = await resp.json();
    } catch (err) {
        console.error("[i18n] Erro ao carregar traduções:", err);
        if (lang !== "pt") await loadTranslations("pt");
    }
}

function t(key, vars = {}) {
    let text = currentTranslations[key] || key;
    Object.entries(vars).forEach(([k, v]) => {
        text = text.replaceAll(`{${k}}`, v);
    });
    return text;
}

function applyTranslations() {
    // textContent
    document.querySelectorAll("[data-i18n]").forEach(el => {
        const key = el.getAttribute("data-i18n");
        if (currentTranslations[key] !== undefined) {
            el.textContent = currentTranslations[key];
        }
    });

    // placeholder
    document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
        const key = el.getAttribute("data-i18n-placeholder");
        if (currentTranslations[key] !== undefined) {
            el.setAttribute("placeholder", currentTranslations[key]);
        }
    });

    // title
    document.querySelectorAll("[data-i18n-title]").forEach(el => {
        const key = el.getAttribute("data-i18n-title");
        if (currentTranslations[key] !== undefined) {
            el.setAttribute("title", currentTranslations[key]);
        }
    });

    // page title (<title>)
    const titleEl = document.querySelector("title[data-i18n]");
    if (titleEl) {
        const key = titleEl.getAttribute("data-i18n");
        if (currentTranslations[key]) document.title = currentTranslations[key];
    }

    // botão ativo no seletor
    const current = getCurrentLang();
    document.querySelectorAll(".lang-btn").forEach(btn => {
        btn.classList.toggle("lang-btn--active", btn.dataset.lang === current);
    });

    // rerenderiza lista de PDFs (textos dinâmicos)
    renderPdfList();
}

function getCurrentLang() {
    return localStorage.getItem(LANG_KEY) || "pt";
}

async function setLanguage(lang) {
    localStorage.setItem(LANG_KEY, lang);
    await loadTranslations(lang);
    applyTranslations();
}

async function initLanguageSelector() {
    const nav = document.getElementById("langNav");
    if (!nav) return;

    let languages = [];
    try {
        const resp = await fetch("/languages");
        if (!resp.ok) throw new Error("Falha ao buscar /languages");
        const json = await resp.json();
        languages  = (json.languages || []).filter(l => l.code !== "_labels");
    } catch (err) {
        console.error("[i18n] Erro ao buscar idiomas:", err);
        languages = [{ code: "pt" }, { code: "en" }, { code: "it" }];
    }

    if (!languages.length) return;

    const ul      = document.createElement("ul");
    ul.className  = "lang-selector";
    const current = getCurrentLang();

    languages.forEach(({ code }) => {
        const li  = document.createElement("li");
        const btn = document.createElement("button");
        btn.type              = "button";
        btn.className         = "lang-btn" + (code === current ? " lang-btn--active" : "");
        btn.dataset.lang      = code;
        btn.textContent       = getLangLabel(code);
        btn.setAttribute("aria-label", `Switch language to ${code}`);
        btn.addEventListener("click", () => setLanguage(code));
        li.appendChild(btn);
        ul.appendChild(li);
    });

    nav.appendChild(ul);
}


// ════════════════════════════════════════════════════════════════════
// Estado global
// ════════════════════════════════════════════════════════════════════

let uploadedPdfs = [];


// ════════════════════════════════════════════════════════════════════
// Alerta personalizado
// ════════════════════════════════════════════════════════════════════

function showAlert(message, onConfirm) {
    const overlay    = document.getElementById("alertOverlay");
    const msgEl      = document.getElementById("alertMessage");
    const btnConfirm = document.getElementById("alertConfirm");
    const btnCancel  = document.getElementById("alertCancel");

    msgEl.textContent = message;
    overlay.classList.remove("hidden");

    const newConfirm = btnConfirm.cloneNode(true);
    const newCancel  = btnCancel.cloneNode(true);
    btnConfirm.replaceWith(newConfirm);
    btnCancel.replaceWith(newCancel);

    document.getElementById("alertConfirm").textContent = t("alert_confirm");
    document.getElementById("alertCancel").textContent  = t("alert_cancel");

    document.getElementById("alertConfirm").addEventListener("click", () => {
        overlay.classList.add("hidden");
        onConfirm();
    });
    document.getElementById("alertCancel").addEventListener("click", () => {
        overlay.classList.add("hidden");
    });
}

document.getElementById("alertOverlay").addEventListener("click", function(e) {
    if (e.target === this) this.classList.add("hidden");
});


// ════════════════════════════════════════════════════════════════════
// Mensagem de feedback
// ════════════════════════════════════════════════════════════════════

function showMsg(text, type) {
    const msgEl       = document.getElementById("uploadMsg");
    msgEl.className   = `msg ${type}`;
    msgEl.textContent = text;
}


// ════════════════════════════════════════════════════════════════════
// Lista de PDFs
// ════════════════════════════════════════════════════════════════════

async function loadPdfList() {
    try {
        const resp   = await fetch("/pdfs");
        const json   = await resp.json();
        uploadedPdfs = json.pdfs || [];
        renderPdfList();
    } catch (err) {
        console.error("Erro ao carregar lista de PDFs:", err);
        showMsg(t("msg_load_error"), "error");
    }
}

function renderPdfList() {
    const container = document.getElementById("pdfListContainer");
    const list      = document.getElementById("pdfList");
    const count     = document.getElementById("pdfCount");

    list.innerHTML = "";

    if (!uploadedPdfs.length) {
        container.classList.add("hidden");
        return;
    }

    container.classList.remove("hidden");

    const totalChunks = uploadedPdfs.reduce((acc, p) => acc + (p.chunks || 0), 0);
    const totalImages = uploadedPdfs.reduce((acc, p) => acc + (p.image_chunks || 0), 0);

    count.textContent = t("pdf_count", {
        n:      uploadedPdfs.length,
        chunks: totalChunks,
        images: totalImages,
    });

    uploadedPdfs.forEach(pdf => {
        const topicsHtml = pdf.topics && pdf.topics.length
            ? `<div class="pdf-topics">
                 ${pdf.topics.map(tp => `<span class="topic-tag">${tp}</span>`).join("")}
               </div>`
            : "";

        const summaryHtml = pdf.summary
            ? `<div class="pdf-summary">${pdf.summary}</div>`
            : "";

        const li = document.createElement("li");
        li.className = "pdf-item";
        li.innerHTML = `
            <div class="pdf-info">
                <div class="pdf-header">
                    <span class="pdf-icon">📎</span>
                    <strong class="pdf-name">${pdf.filename}</strong>
                    <span class="pdf-meta">
                        ${pdf.text_chunks || 0} ${t("label_text")} · ${pdf.image_chunks || 0} ${t("label_img")}
                    </span>
                </div>
                ${summaryHtml}
                ${topicsHtml}
            </div>
            <button
                class="btn-delete"
                data-id="${pdf.file_id}"
                data-name="${pdf.filename}"
                title="${t("remove_title")}"
                aria-label="${t("remove_title")}"
            >
                🗑️
            </button>
        `;
        list.appendChild(li);
    });

    list.querySelectorAll(".btn-delete").forEach(btn => {
        btn.addEventListener("click", () => deletePdf(btn.dataset.id, btn.dataset.name));
    });
}


// ════════════════════════════════════════════════════════════════════
// Upload com polling de status
// ════════════════════════════════════════════════════════════════════

document.getElementById("uploadForm").addEventListener("submit", async function(e) {
    e.preventDefault();

    const fileInput = document.getElementById("fileInput");
    const uploadBtn = document.getElementById("uploadBtn");

    if (!fileInput.files.length) {
        showMsg(t("msg_select_file"), "error");
        return;
    }

    showMsg(t("msg_sending"), "info");
    uploadBtn.disabled = true;

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    try {
        const resp = await fetch("/upload", { method: "POST", body: formData });
        const json = await resp.json();

        if (!resp.ok) {
            // Tenta mapear mensagens do backend para chaves de tradução
            const detail = json.detail || "";
            if (detail.includes("já foi enviado")) {
                showMsg(t("msg_already_sent"), "error");
            } else if (detail.includes("Apenas arquivos PDF")) {
                showMsg(t("msg_only_pdf"), "error");
            } else {
                showMsg(detail || t("msg_send_error"), "error");
            }
            uploadBtn.disabled = false;
            return;
        }

        fileInput.value = "";
        await pollUploadStatus(json.file_id, json.filename);

    } catch (err) {
        showMsg(t("msg_conn_error"), "error");
    } finally {
        uploadBtn.disabled = false;
    }
});


async function pollUploadStatus(fileId, filename) {
    const INTERVAL   = 3000;
    const WARN_AFTER = 120;
    let   tries      = 0;

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
                    showMsg(`${t("msg_waiting")} (${tempo})`, "info");
                    return;
                }

                const json = await resp.json();

                if (json.status === "concluido") {
                    clearInterval(interval);
                    showMsg(json.message, "success");
                    uploadedPdfs.push({
                        file_id:      json.file_id,
                        filename:     json.filename,
                        chunks:       json.chunks,
                        text_chunks:  json.text_chunks,
                        image_chunks: json.image_chunks,
                        summary:      json.summary || "",
                        topics:       json.topics  || [],
                    });
                    renderPdfList();
                    resolve();
                    return;
                }

                if (json.status === "erro") {
                    clearInterval(interval);
                    showMsg(json.message, "error");
                    resolve();
                    return;
                }

                if (tries === WARN_AFTER) {
                    showMsg(
                        `⏳ ${json.message} (${tempo}) — ${t("msg_large_pdf")}`,
                        "info"
                    );
                    return;
                }

                showMsg(`⏳ ${json.message} (${tempo})`, "info");

            } catch (err) {
                if (tries >= WARN_AFTER + 20) {
                    clearInterval(interval);
                    showMsg(t("msg_conn_status"), "error");
                    resolve();
                }
            }
        }, INTERVAL);
    });
}


// ════════════════════════════════════════════════════════════════════
// Excluir PDF individual
// ════════════════════════════════════════════════════════════════════

function deletePdf(fileId, filename) {
    showAlert(
        t("alert_delete_msg", { filename }),
        async () => {
            try {
                const resp = await fetch(`/delete-pdf/${fileId}`, { method: "DELETE" });
                const json = await resp.json();

                if (resp.ok) {
                    uploadedPdfs = uploadedPdfs.filter(p => p.file_id !== fileId);
                    renderPdfList();
                    showMsg(json.message, "success");
                } else {
                    showMsg(json.detail || t("msg_remove_error"), "error");
                }
            } catch (err) {
                showMsg(t("msg_remove_conn"), "error");
            }
        }
    );
}


// ════════════════════════════════════════════════════════════════════
// Limpar tudo
// ════════════════════════════════════════════════════════════════════

document.getElementById("clearAllBtn").addEventListener("click", function() {
    showAlert(
        t("alert_clear_msg"),
        async () => {
            try {
                const resp = await fetch("/clear-all", { method: "DELETE" });
                const json = await resp.json();

                if (resp.ok) {
                    uploadedPdfs = [];
                    renderPdfList();
                    document.getElementById("searchResults").innerHTML = "";
                    showMsg(json.message, "success");
                } else {
                    showMsg(json.detail || t("msg_clear_error"), "error");
                }
            } catch (err) {
                showMsg(t("msg_clear_conn"), "error");
            }
        }
    );
});


// ════════════════════════════════════════════════════════════════════
// Busca
// ════════════════════════════════════════════════════════════════════

document.getElementById("searchForm").addEventListener("submit", async function(e) {
    e.preventDefault();

    const query     = document.getElementById("queryInput").value.trim();
    const topK      = document.getElementById("topKInput").value;
    const container = document.getElementById("searchResults");

    if (!query) {
        container.innerHTML = `<div class="msg error">${t("msg_no_query")}</div>`;
        return;
    }

    if (!uploadedPdfs.length) {
        container.innerHTML = `<div class="msg error">${t("msg_no_pdf")}</div>`;
        return;
    }

    container.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            ${t("msg_searching")}
        </div>
    `;

    const formData = new FormData();
    formData.append("query", query);
    formData.append("top_k", topK);

    try {
        const resp = await fetch("/search", { method: "POST", body: formData });
        const json = await resp.json();

        container.innerHTML = "";
        const answerDiv     = document.createElement("div");
        answerDiv.className = "result-item";
        answerDiv.innerHTML = `<p class="text">${json.answer || t("msg_no_answer")}</p>`;
        container.appendChild(answerDiv);

    } catch (err) {
        container.innerHTML = `<div class="msg error">${t("msg_search_error")}</div>`;
    }
});


// ════════════════════════════════════════════════════════════════════
// Inicialização
// ════════════════════════════════════════════════════════════════════

(async () => {
    await fetchLangLabels();

    const savedLang = getCurrentLang();
    await loadTranslations(savedLang);
    await initLanguageSelector();
    applyTranslations();
    await loadPdfList();
})();
