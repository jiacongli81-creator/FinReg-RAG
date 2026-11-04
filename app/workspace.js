/* Workspace controls for history, favorites, document tags and update scans. */
const jsonOptions = (method, body) => ({method, headers: {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body)});
const dateText = value => value ? new Date(value).toLocaleString('zh-CN') : '';
const empty = message => `<div class="placeholder"><strong>${esc(message)}</strong></div>`;
const answerCard = (item, kind) => `<div class="source"><strong>${esc(item.question)}</strong>
    <div class="note">${esc(dateText(item.created_at))} · ${item.sources?.length || 0} 条依据</div>
    <p style="max-height:none;white-space:pre-wrap">${esc(item.answer)}</p>
    <button class="link" data-open-answer="${esc(kind)}:${esc(item.id)}">查看回答和来源</button>
    ${kind === 'history' ? `<button class="link" data-favorite-history="${esc(item.id)}">☆ 收藏</button>
    <button class="link" data-delete-history="${esc(item.id)}">删除记录</button>` :
    `<button class="link" data-delete-favorite="${esc(item.id)}">取消收藏</button>`}</div>`;

async function loadHistory() {
    const term = $('#historyFilter').value.trim();
    try {
        const items = await api('/history?' + new URLSearchParams({query: term, limit: '200'}));
        $('#historyList').innerHTML = items.length ? items.map(item => answerCard(item, 'history')).join('') : empty('没有匹配的问答记录');
    } catch (error) { $('#historyList').innerHTML = empty(error.message); }
}
async function loadFavorites() {
    const term = $('#favoriteFilter').value.trim();
    try {
        const items = await api('/favorites?' + new URLSearchParams({query: term}));
        $('#favoriteList').innerHTML = items.length ? items.map(item => answerCard(item, 'favorite')).join('') : empty('还没有收藏的回答');
    } catch (error) { $('#favoriteList').innerHTML = empty(error.message); }
}
async function loadTags() {
    try {
        const tags = await api('/tags');
        $('#tagList').innerHTML = tags.length ? tags.map(tag => `<div class="source"><strong>${esc(tag.name)}</strong>
            <p>已关联 ${tag.document_count} 份文档</p>
            <button class="link" data-rename-tag="${esc(tag.id)}" data-name="${esc(tag.name)}">重命名</button>
            <button class="link" data-delete-tag="${esc(tag.id)}">删除标签</button></div>`).join('') : empty('还没有标签');
    } catch (error) { $('#tagList').innerHTML = empty(error.message); }
}
async function loadUpdates() {
    try {
        const runs = await api('/updates');
        const last = runs[0];
        $('#updateAdded').textContent = last?.added ?? 0;
        $('#updateChanged').textContent = last?.updated ?? 0;
        $('#updateSkipped').textContent = last?.skipped ?? 0;
        $('#updateFailed').textContent = last?.failed ?? 0;
        $('#updateList').innerHTML = runs.length ? runs.map(run => `<div class="source">
            <strong>${esc(dateText(run.created_at))}</strong>
            <p>新增 ${run.added} · 更新 ${run.updated} · 跳过 ${run.skipped} · 失败 ${run.failed}</p>
            ${run.details.map(item => `<p>${esc(item.path)}：${esc(item.status)} ${esc(item.error || '')}</p>`).join('')}
            </div>`).join('') : empty('尚未执行扫描');
    } catch (error) { $('#updateList').innerHTML = empty(error.message); }
}

document.querySelectorAll('[data-page],[data-go]').forEach(button => button.addEventListener('click', () => {
    const target = button.dataset.page || button.dataset.go;
    if (target === 'history') loadHistory();
    if (target === 'favorites') loadFavorites();
    if (target === 'tags') loadTags();
    if (target === 'updates') loadUpdates();
}));
$('#historyForm').onsubmit = event => {event.preventDefault(); loadHistory()};
$('#favoriteForm').onsubmit = event => {event.preventDefault(); loadFavorites()};
$('#tagForm').onsubmit = async event => {
    event.preventDefault();
    const name = $('#tagName').value.trim();
    if (!name) return;
    try { await api('/tags', jsonOptions('POST', {name})); $('#tagName').value = ''; await loadTags(); toast('标签已创建'); }
    catch (error) { toast(error.message); }
};
$('#scanUpdates').onclick = async () => {
    const button = $('#scanUpdates'); button.disabled = true; button.textContent = '扫描中…';
    try { const run = await api('/updates/scan', {method: 'POST'}); await loadUpdates(); await loadDocs();
        toast(`扫描完成：新增 ${run.added}，更新 ${run.updated}，失败 ${run.failed}`); }
    catch (error) { toast(error.message); }
    finally { button.disabled = false; button.textContent = '↻ 扫描资料目录'; }
};

document.addEventListener('click', async event => {
    const button = event.target.closest('[data-favorite-history],[data-delete-history],[data-delete-favorite],[data-open-answer],[data-rename-tag],[data-delete-tag],[data-doc-tags]');
    if (!button) return;
    try {
        if (button.dataset.favoriteHistory) {
            await api('/favorites', jsonOptions('POST', {history_id: Number(button.dataset.favoriteHistory)}));
            button.textContent = '★ 已收藏'; toast('回答已收藏');
            if ($('#page-favorites').classList.contains('active')) await loadFavorites();
        } else if (button.dataset.deleteHistory) {
            if (!confirm('删除这条问答历史？已收藏的副本会保留。')) return;
            await api('/history/' + encodeURIComponent(button.dataset.deleteHistory), {method: 'DELETE'});
            await loadHistory(); toast('历史记录已删除');
        } else if (button.dataset.deleteFavorite) {
            await api('/favorites/' + encodeURIComponent(button.dataset.deleteFavorite), {method: 'DELETE'});
            await loadFavorites(); toast('已取消收藏');
        } else if (button.dataset.openAnswer) {
            const [kind, id] = button.dataset.openAnswer.split(':');
            const item = kind === 'history' ? await api('/history/' + encodeURIComponent(id)) :
                (await api('/favorites')).find(value => value.id === id);
            if (!item) throw Error('没有找到记录');
            page('ask'); window.currentHistoryId = item.history_id || (kind === 'history' ? item.id : null);
            $('#answerArea').innerHTML = `<div class="answer"><strong>问题</strong><p>${esc(item.question)}</p>
                <strong>回答</strong><p>${esc(item.answer)}</p>
                ${window.currentHistoryId ? `<button class="link" data-favorite-history="${window.currentHistoryId}">☆ 收藏</button>` : ''}</div>`;
            $('#sources').innerHTML = item.sources?.length ? item.sources.map(sourceCard).join('') : empty('没有来源');
            $('#sourceCount').textContent = (item.sources?.length || 0) + ' 条';
        } else if (button.dataset.renameTag) {
            const name = prompt('新的标签名称', button.dataset.name)?.trim(); if (!name) return;
            await api('/tags/' + encodeURIComponent(button.dataset.renameTag), jsonOptions('PUT', {name}));
            await loadTags(); toast('标签已重命名');
        } else if (button.dataset.deleteTag) {
            if (!confirm('删除该标签及其文档关联？')) return;
            await api('/tags/' + encodeURIComponent(button.dataset.deleteTag), {method: 'DELETE'});
            await loadTags(); toast('标签已删除');
        } else if (button.dataset.docTags) {
            const id = button.dataset.docTags;
            const [tags, assigned] = await Promise.all([api('/tags'), api('/documents/' + encodeURIComponent(id) + '/tags')]);
            if (!tags.length) { toast('请先到标签管理创建标签'); page('tags'); return; }
            const choices = tags.map((tag, index) => `${index + 1}. ${tag.name}`).join('\n');
            const current = assigned.map(item => tags.findIndex(tag => tag.id === item.id) + 1).join(',');
            const entry = prompt(`选择标签序号，多个用逗号分隔；留空清除：\n${choices}`, current);
            if (entry === null) return;
            const numbers = entry.trim() ? entry.split(/[,，\s]+/).map(Number) : [];
            if (numbers.some(n => !Number.isInteger(n) || n < 1 || n > tags.length)) throw Error('标签序号无效');
            await api('/documents/' + encodeURIComponent(id) + '/tags',
                jsonOptions('PUT', {tag_ids: [...new Set(numbers)].map(n => tags[n - 1].id)}));
            toast('文档标签已更新');
        }
    } catch (error) { toast(error.message); }
});
