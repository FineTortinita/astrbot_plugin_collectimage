const API_BASE = '';

let currentPage = 0;
let pageSize = 12;
let totalImages = 0;
let currentImageId = null;
let currentFilter = 'all';
let isSearchMode = false;
let currentSearchKeyword = '';
let detailModal = null;
let loginPage, mainPage, loginForm, loginError, imageGrid, imageCount;
let _resizeTimer = null;
let logPollTimer = null;
let logCursor = 0;
let currentLoadedImages = [];
const MAX_LOG_LINES = 1000;
let listRevision = 0;
let detailRevision = 0;
let detailDirty = false;
let confirmBusy = false;
let isLoadingMore = false;
let hasMoreImages = true;
let infiniteObserver = null;
let currentConfigCategory = 'all';

function setupInfiniteScroll() {
    const sentinel = document.getElementById('scroll-load-sentinel');
    const loadMoreBtn = document.getElementById('load-more-btn');
    if (loadMoreBtn) {
        loadMoreBtn.addEventListener('click', () => {
            if (!isLoadingMore && hasMoreImages) {
                loadImages(true);
            }
        });
    }
    if (!sentinel || typeof IntersectionObserver === 'undefined') return;
    if (infiniteObserver) infiniteObserver.disconnect();
    infiniteObserver = new IntersectionObserver((entries) => {
        const entry = entries[0];
        if (!entry || !entry.isIntersecting) return;
        const tab = document.getElementById('tab-images');
        if (!tab || tab.classList.contains('hidden')) return;
        if (!isLoadingMore && hasMoreImages && currentLoadedImages.length > 0 && currentLoadedImages.length < totalImages) {
            loadImages(true);
        }
    }, { root: null, rootMargin: '260px 0px', threshold: 0.01 });
    infiniteObserver.observe(sentinel);
}

function updateScrollSentinelUI() {
    const statusEl = document.getElementById('scroll-load-status');
    const btnEl = document.getElementById('load-more-btn');
    const sentinel = document.getElementById('scroll-load-sentinel');
    if (!sentinel || !statusEl || !btnEl) return;

    const loaded = currentLoadedImages.length;
    hasMoreImages = loaded < totalImages;

    if (totalImages === 0) {
        sentinel.classList.add('hidden');
        return;
    }
    sentinel.classList.remove('hidden');

    if (isLoadingMore) {
        statusEl.textContent = `正在动态加载更多图片 (${loaded} / ${totalImages})...`;
        btnEl.disabled = true;
        btnEl.classList.remove('hidden');
    } else if (hasMoreImages) {
        statusEl.textContent = `已加载 ${loaded} / ${totalImages} 张图片 · 向下滚动自动加载更多`;
        btnEl.disabled = false;
        btnEl.classList.remove('hidden');
    } else {
        statusEl.textContent = `已全部加载完毕（共 ${totalImages} 张图片）`;
        btnEl.classList.add('hidden');
    }
}
function clearInspector() {
    currentImageId = null;
    detailRevision++;
    detailDirty = false;
    document.querySelector('.character-list')?.replaceChildren();
    document.getElementById('detail-description').value = '';
    document.getElementById('detail-tags').replaceChildren();
    ['detail-image', 'zoom-modal-image'].forEach(id => document.getElementById(id).removeAttribute('src'));
    ['dock-frame-id','detail-filename','detail-group','detail-sender','detail-time','dock-confirm-status'].forEach(id => document.getElementById(id).textContent = '未选择');
    setInspectorEnabled(false);
}
function setInspectorEnabled(enabled) {
    document.querySelectorAll('#inspector-single button,#inspector-single input,#inspector-single textarea').forEach(el => el.disabled = !enabled);
}
async function allowDiscard() {
    return !detailDirty || await showConfirm('尚未保存', '当前角色或描述尚未保存。放弃修改并继续？');
}


// HTML 转义，防止存储型 XSS
function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function getGridCols() {
    const grid = document.getElementById('image-grid');
    return grid ? getComputedStyle(grid).gridTemplateColumns.split(' ').length : 2;
}

function calculatePageSize() {
    const cols = getGridCols();
    return cols * 3;
}

window.addEventListener('resize', () => {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(() => {
        if (detailDirty || mainPage?.classList.contains('hidden')) return;
        const tab = document.getElementById('tab-images');
        if (tab && !tab.classList.contains('hidden')) {
            pageSize = calculatePageSize();
        }
    }, 250);
});

// 右下角非占用气泡反馈（pointer-events 仅作用于气泡本身，不遮挡页面操作）
const TOAST_ICONS = { success: '✓', error: '✕', warning: '!', info: 'i' };
const TOAST_MAX = 5;

function showToast(message, type = 'success', { persistent = false, duration } = {}) {
    const stack = document.getElementById('toast-stack');
    const kind = TOAST_ICONS[type] ? type : 'success';
    const toast = document.createElement('div');
    toast.className = `toast-bubble toast-${kind}`;
    toast.setAttribute('role', kind === 'error' ? 'alert' : 'status');

    const icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = TOAST_ICONS[kind];
    const text = document.createElement('span');
    text.className = 'toast-text';
    text.textContent = String(message ?? '');
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast-close';
    close.setAttribute('aria-label', '关闭提示');
    close.textContent = '×';
    toast.append(icon, text, close);

    let timer = null;
    const ttl = duration ?? (kind === 'error' ? 5000 : 2800);
    const dismiss = () => {
        clearTimeout(timer);
        if (!toast.isConnected || toast.classList.contains('toast-leaving')) return;
        toast.classList.add('toast-leaving');
        setTimeout(() => toast.remove(), 220);
    };
    const arm = () => { if (!persistent) { clearTimeout(timer); timer = setTimeout(dismiss, ttl); } };
    close.addEventListener('click', dismiss);
    toast.addEventListener('mouseenter', () => clearTimeout(timer));
    toast.addEventListener('mouseleave', arm);

    if (stack) {
        stack.appendChild(toast);
        const live = stack.querySelectorAll('.toast-bubble:not(.toast-leaving)');
        for (let i = 0; i < live.length - TOAST_MAX; i++) live[i].remove();
        arm();
    }
    return {
        update(msg) { text.textContent = String(msg ?? ''); },
        close: dismiss,
    };
}

// 自定义确认弹窗
function showConfirm(title, message) {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirm-modal');
        const overlay = document.getElementById('confirm-overlay');
        const titleEl = document.getElementById('confirm-title');
        const messageEl = document.getElementById('confirm-message');
        const cancelBtn = document.getElementById('confirm-cancel');
        const okBtn = document.getElementById('confirm-ok');

        if (!modal) {
            resolve(false);
            return;
        }

        titleEl.textContent = title;
        messageEl.textContent = message;
        const priorFocus = document.activeElement;
        modal.classList.remove('hidden');
        cancelBtn.focus();
        function dialogKey(e) {
            if (e.key === 'Escape') { e.preventDefault(); handleCancel(); }
            if (e.key === 'Tab') { e.preventDefault(); (document.activeElement === cancelBtn ? okBtn : cancelBtn).focus(); }
        }
        modal.addEventListener('keydown', dialogKey);
        function cleanup() {
            modal.removeEventListener('keydown', dialogKey);
            priorFocus?.focus();
            cancelBtn.removeEventListener('click', handleCancel);
            okBtn.removeEventListener('click', handleOk);
            overlay.removeEventListener('click', handleOverlay);
        }
        function handleCancel() { modal.classList.add('hidden'); cleanup(); resolve(false); }
        function handleOk() { modal.classList.add('hidden'); cleanup(); resolve(true); }
        function handleOverlay() { modal.classList.add('hidden'); cleanup(); resolve(false); }

        cancelBtn.addEventListener('click', handleCancel);
        okBtn.addEventListener('click', handleOk);
        overlay.addEventListener('click', handleOverlay);
    });
}

const THEME_STORAGE_KEY = 'collectimage_webui_theme';

function getPreferredTheme() {
    try {
        const qTheme = new URLSearchParams(window.location.search).get('theme');
        if (qTheme === 'dark' || qTheme === 'light') return qTheme;
        const saved = localStorage.getItem(THEME_STORAGE_KEY);
        if (saved === 'dark' || saved === 'light') return saved;
    } catch (_) {}
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark';
    }
    return 'light';
}

function applyTheme(theme) {
    const mode = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', mode);
    try {
        localStorage.setItem(THEME_STORAGE_KEY, mode);
    } catch (_) {}
    document.querySelectorAll('.theme-toggle-btn').forEach(btn => {
        btn.textContent = mode === 'dark' ? '☀ 亮色模式' : '◐ 暗色模式';
        btn.title = mode === 'dark' ? '切换到柔和亮色模式' : '切换到护眼暗色模式';
    });
}

function setupThemeToggle() {
    applyTheme(getPreferredTheme());
    document.querySelectorAll('.theme-toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const current = document.documentElement.getAttribute('data-theme') || 'light';
            applyTheme(current === 'dark' ? 'light' : 'dark');
        });
    });
}

function safeRefreshIcons() {
    if (typeof window.lucide !== 'undefined' && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
    }
}

// 页面加载时检查登录状态
document.addEventListener('DOMContentLoaded', async () => {
    setupThemeToggle();
    loginPage = document.getElementById('login-page');
    mainPage = document.getElementById('main-page');
    loginForm = document.getElementById('login-form');
    loginError = document.getElementById('login-error');
    imageGrid = document.getElementById('image-grid');
    imageCount = document.getElementById('image-count');
    detailModal = document.getElementById('detail-modal');

    setInspectorEnabled(false);
    document.getElementById('character-editor').addEventListener('input', () => detailDirty = true);
    document.getElementById('detail-description').addEventListener('input', () => detailDirty = true);
    document.getElementById('detail-modal-overlay').addEventListener('click', handleDetailOverlayClick);
    document.querySelectorAll('#import-modal,#alias-modal,#detail-modal,#confirm-modal').forEach(modal => {
        modal.setAttribute('role','dialog');
        modal.setAttribute('aria-modal','true');
        modal.setAttribute('aria-label', modal.querySelector('.retro-titlebar')?.textContent.trim() || '对话框');
        modal.addEventListener('keydown', e => {
            if (e.key === 'Escape' && modal.id !== 'confirm-modal') modal.classList.add('hidden');
        });
    });
    bindEventListeners();
    setupInfiniteScroll();
    safeRefreshIcons();
    await checkAuth();
});

// 绑定所有事件监听器
function bindEventListeners() {
    // 登录表单提交
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const password = document.getElementById('password').value;

            try {
                const response = await fetch(`${API_BASE}/api/auth/login`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password })
                });
                const data = await response.json();

                if (data.success) {
                    showMainPage();
                    loadImages();
                    refreshMonitorFacts();
                } else {
                    loginError.textContent = data.error || '登录失败';
                    loginError.classList.remove('hidden');
                }
            } catch (e) {
                console.error('Login error:', e);
                loginError.textContent = '网络错误';
                loginError.classList.remove('hidden');
            }
        });
    }

    // 退出登录
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            await fetch(`${API_BASE}/api/auth/logout`, { method: 'POST' });
            stopLogPolling();
            showLoginPage();
        });
    }

    // 搜索
    const searchBtn = document.getElementById('search-btn');
    if (searchBtn) {
        searchBtn.addEventListener('click', () => {
            const keyword = document.getElementById('search-keyword')?.value?.trim() || '';
            if (keyword) {
                searchImagesWithAlias(keyword);
            } else {
                currentPage = 0;
                isSearchMode = false;
                currentSearchKeyword = '';
                loadImages();
            }
        });
    }

    // 搜索框回车搜索
    const keywordInput = document.getElementById('search-keyword');
    if (keywordInput) {
        keywordInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                const keyword = keywordInput.value?.trim() || '';
                if (keyword) {
                    searchImagesWithAlias(keyword);
                } else {
                    currentPage = 0;
                    isSearchMode = false;
                    currentSearchKeyword = '';
                    loadImages();
                }
            }
        });
    }

    // 快捷检索词按钮
    document.querySelectorAll('.quick-query-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const q = btn.dataset.q || '';
            const input = document.getElementById('search-keyword');
            if (input) input.value = q;
            if (q) {
                searchImagesWithAlias(q);
            } else {
                currentPage = 0;
                isSearchMode = false;
                currentSearchKeyword = '';
                loadImages();
            }
        });
    });

    // 状态筛选按钮 (全部 / 未确认 / 已确认 / 统计)
    document.querySelectorAll('.sidebar-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelectorAll('.sidebar-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');

            currentFilter = item.dataset.filter;
            isSearchMode = false;
            currentSearchKeyword = '';

            const hintEl = document.getElementById('grid-status-hint');
            if (hintEl) {
                hintEl.textContent = ({all:'全部图片',confirmed:'已确认',unconfirmed:'待校对',stats:'统计'})[currentFilter] || '全部图片';
            }

            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.add('hidden');
            });

            if (currentFilter === 'stats') {
                document.getElementById('tab-stats')?.classList.remove('hidden');
                loadStats();
            } else {
                document.getElementById('tab-images')?.classList.remove('hidden');
                currentPage = 0;
                loadImages();
            }
        });
    });

    // 统计天数切换
    const statsDaysSelect = document.getElementById('stats-days');
    if (statsDaysSelect) {
        statsDaysSelect.addEventListener('change', () => {
            loadStats();
        });
    }

    // 分页事件
    const firstPageBtn = document.getElementById('first-page');
    const prevPageBtn = document.getElementById('prev-page');
    const nextPageBtn = document.getElementById('next-page');
    const lastPageBtn = document.getElementById('last-page');
    const goPageBtn = document.getElementById('go-page');
    const pageInput = document.getElementById('page-input');

    if (firstPageBtn) {
        firstPageBtn.addEventListener('click', () => {
            if (currentPage > 0) {
                currentPage = 0;
                loadImages();
            }
        });
    }

    if (prevPageBtn) {
        prevPageBtn.addEventListener('click', () => {
            if (currentPage > 0) {
                currentPage--;
                loadImages();
            }
        });
    }

    if (nextPageBtn) {
        nextPageBtn.addEventListener('click', () => {
            const totalPages = Math.ceil(totalImages / pageSize) || 1;
            if (currentPage < totalPages - 1) {
                currentPage++;
                loadImages();
            }
        });
    }

    if (lastPageBtn) {
        lastPageBtn.addEventListener('click', () => {
            const totalPages = Math.ceil(totalImages / pageSize) || 1;
            if (currentPage < totalPages - 1) {
                currentPage = totalPages - 1;
                loadImages();
            }
        });
    }

    if (goPageBtn) {
        goPageBtn.addEventListener('click', () => {
            const totalPages = Math.ceil(totalImages / pageSize) || 1;
            const input = document.getElementById('page-input');
            let targetPage = parseInt(input?.value || '1');

            if (isNaN(targetPage) || targetPage < 1) targetPage = 1;
            if (targetPage > totalPages) targetPage = totalPages;

            currentPage = targetPage - 1;
            loadImages();
        });
    }

    if (pageInput) {
        pageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                const goBtn = document.getElementById('go-page');
                if (goBtn) goBtn.click();
            }
        });
    }

    bindBatchControls();

    const detailCloseBtn = document.querySelector('#detail-modal .close');
    if (detailCloseBtn && detailModal) {
        detailCloseBtn.addEventListener('click', () => {
            detailModal.classList.add('hidden');
        });
    }

    // 保存详情 (常驻检片槽)
    const saveDetailBtn = document.getElementById('save-detail-btn');
    if (saveDetailBtn) {
        saveDetailBtn.addEventListener('click', async () => {
            if (!currentImageId) return;
            const character = getCharacterJson();
            const descriptionInput = document.getElementById('detail-description');
            const description = descriptionInput?.value || '';

            try {
                const response = await fetch(`${API_BASE}/api/images/${currentImageId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ character, description })
                });
                const data = await response.json();

                if (data.success) {
                    detailDirty = false;
                    showToast('角色与描述已保存', 'success');
                    loadImages();
                } else {
                    showToast('保存失败: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('保存失败: ' + e, 'error');
            }
        });
    }

    // 盖章确认按钮
    const confirmBtn = document.getElementById('confirm-btn');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', async () => {
            if (!currentImageId) return;
            await setConfirmStatus(currentImageId, true, true);
        });
    }

    // 取消确认按钮
    const unconfirmBtn = document.getElementById('unconfirm-btn');
    if (unconfirmBtn) {
        unconfirmBtn.addEventListener('click', async () => {
            if (!currentImageId) return;
            await setConfirmStatus(currentImageId, false, false);
        });
    }

    // 空格键快捷盖章确认归档
    window.addEventListener('keydown', async (e) => {
        if (e.key === 'Escape' && batchMode && !e.defaultPrevented && !e.target.closest?.('[role="dialog"]') && !document.querySelector('[role="dialog"]:not(.hidden)')) {
            e.preventDefault();
            setBatchMode(false);
            return;
        }
        const tag = document.activeElement?.tagName;
        if (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(tag)) return;
        if (mainPage?.classList.contains('hidden') || e.ctrlKey || e.altKey || e.metaKey) return;
        if (e.repeat || document.querySelector('[role="dialog"]:not(.hidden)')) return;
        const imagesTab = document.getElementById('tab-images');
        if (!imagesTab || imagesTab.classList.contains('hidden')) return;
        if (batchMode) return;
        if (e.code === 'Space' && currentImageId) {
            e.preventDefault();
            await setConfirmStatus(currentImageId, true, true);
        }
    });

    // AI 重新分析
    const reanalyzeBtn = document.getElementById('reanalyze-btn');
    if (reanalyzeBtn) {
        reanalyzeBtn.addEventListener('click', async () => {
            if (!currentImageId) return;
            if (!await showConfirm('重新分析', '确定要重新分析这张图片吗？')) return;

            reanalyzeBtn.disabled = true;
            reanalyzeBtn.textContent = '分析中...';

            try {
                const response = await fetch(`${API_BASE}/api/images/${currentImageId}/reanalyze`, {
                    method: 'POST'
                });
                const data = await response.json();

                if (data.success) {
                    showToast('重新分析完成', 'success');
                    await openDetail(currentImageId);
                    loadImages();
                } else {
                    showToast('重新分析失败: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('重新分析失败: ' + e, 'error');
            } finally {
                reanalyzeBtn.disabled = false;
                reanalyzeBtn.textContent = '↻ VLM 重分析';
            }
        });
    }

    // 识别角色
    const recognizeBtn = document.getElementById('recognize-btn');
    if (recognizeBtn) {
        recognizeBtn.addEventListener('click', async () => {
            if (!currentImageId) return;
            if (!await allowDiscard()) return;
            if (!await showConfirm('识别角色', '使用 AnimeTrace 识别角色（未命中时回退 VLM），结果将覆盖当前角色。继续？')) return;

            recognizeBtn.disabled = true;
            recognizeBtn.textContent = '识别中...';

            try {
                const response = await fetch(`${API_BASE}/api/images/${currentImageId}/recognize_character`, {
                    method: 'POST'
                });
                const data = await response.json();

                if (data.success) {
                    if (data.source === 'none') {
                        showToast('未识别到角色，已保留原有数据', 'warning');
                    } else {
                        showToast(`角色识别完成（${data.source === 'vlm' ? 'VLM 回退' : 'AnimeTrace'}）`, 'success');
                        updateCardCharacter(currentImageId, data.character);
                        await openDetail(currentImageId);
                    }
                } else {
                    showToast('角色识别失败: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('角色识别失败: ' + e, 'error');
            } finally {
                recognizeBtn.disabled = false;
                recognizeBtn.textContent = '◎ 识别角色';
            }
        });
    }

    // 删除图片
    const deleteBtn = document.getElementById('delete-btn');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', async () => {
            if (!currentImageId) return;
            if (!await showConfirm('删除图片', '确定要删除这张图片吗？此操作不可恢复！')) return;

            try {
                const response = await fetch(`${API_BASE}/api/images/${currentImageId}`, {
                    method: 'DELETE'
                });
                const data = await response.json();

                if (data.success) {
                    showToast('删除成功', 'success');
                    if (detailModal) detailModal.classList.add('hidden');
                    currentImageId = null;
                    loadImages();
                    refreshMonitorFacts();
                } else {
                    showToast('删除失败: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('删除失败: ' + e, 'error');
            }
        });
    }

    // 顶部工作域标签切换
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.dataset.tab;

            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.add('hidden');
            });
            document.getElementById(`tab-${tabName}`)?.classList.remove('hidden');

            const sidebar = document.getElementById('sidebar');
            if (sidebar) {
                if (tabName === 'images') {
                    sidebar.classList.remove('hidden');
                } else {
                    sidebar.classList.add('hidden');
                }
            }
            if (tabName === 'logs') {
                startLogPolling(true);
            } else {
                stopLogPolling();
            }

            if (tabName === 'aliases') {
                aliasCurrentPage = 1;
                loadAliases();
            } else if (tabName === 'images') {
                if (currentFilter === 'stats') {
                    currentFilter = 'all';
                    document.querySelectorAll('.sidebar-item').forEach(item => item.classList.toggle('active', item.dataset.filter === 'all'));
                }
                currentPage = 0;
                loadImages();
            } else if (tabName === 'stats') {
                loadStats();
            } else if (tabName === 'config') {
                loadConfig();
            }
        });
    });

    const logAutoScroll = document.getElementById('log-auto-scroll');
    if (logAutoScroll) {
        logAutoScroll.addEventListener('change', () => {
            if (logAutoScroll.checked) {
                scrollLogsToBottom();
            }
        });
    }

    // 别名分页与筛选
    const aliasPrevBtn = document.getElementById('alias-prev-page');
    const aliasNextBtn = document.getElementById('alias-next-page');
    const aliasPageSizeSelect = document.getElementById('alias-page-size');
    const searchAliasBtn = document.getElementById('search-alias-btn');
    const searchAliasInput = document.getElementById('search-alias');
    const aliasTypeFilter = document.getElementById('alias-type-filter');

    if (aliasPrevBtn) {
        aliasPrevBtn.addEventListener('click', () => {
            if (aliasCurrentPage > 1) {
                aliasCurrentPage--;
                loadAliases();
            }
        });
    }

    if (aliasNextBtn) {
        aliasNextBtn.addEventListener('click', () => {
            if (aliasCurrentPage < aliasTotalPages) {
                aliasCurrentPage++;
                loadAliases();
            }
        });
    }

    if (aliasPageSizeSelect) {
        aliasPageSizeSelect.addEventListener('change', () => {
            aliasCurrentPage = 1;
            loadAliases();
        });
    }

    if (searchAliasBtn) {
        searchAliasBtn.addEventListener('click', () => {
            aliasCurrentPage = 1;
            loadAliases();
        });
    }

    if (searchAliasInput) {
        searchAliasInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                aliasCurrentPage = 1;
                loadAliases();
            }
        });
    }

    if (aliasTypeFilter) {
        aliasTypeFilter.addEventListener('change', () => {
            aliasCurrentPage = 1;
            loadAliases();
        });
    }

    // 导入别名
    const importAliasBtn = document.getElementById('import-alias-btn');
    if (importAliasBtn) {
        importAliasBtn.addEventListener('click', async () => {
            if (!await showConfirm('导入别名', '确定要从 aliases.json 导入别名吗？')) return;

            importAliasBtn.disabled = true;
            importAliasBtn.textContent = '启动中...';

            try {
                const response = await fetch(`${API_BASE}/api/aliases/import`, {
                    method: 'POST'
                });
                const data = await response.json();

                if (data.success) {
                    importAliasBtn.textContent = '导入中...';
                    const progressEl = document.getElementById('import-progress');
                    if (progressEl) progressEl.classList.remove('hidden');
                    startImportPoll();
                } else {
                    showToast('导入失败: ' + data.error, 'error');
                    importAliasBtn.disabled = false;
                    importAliasBtn.textContent = '导入 aliases.json';
                }
            } catch (e) {
                showToast('导入失败: ' + e, 'error');
                importAliasBtn.disabled = false;
                importAliasBtn.textContent = '导入 aliases.json';
            }
        });
    }

    // 停止导入
    const stopImportBtn = document.getElementById('stop-import-btn');
    if (stopImportBtn) {
        stopImportBtn.addEventListener('click', async () => {
            if (!await showConfirm('停止导入', '确定要停止导入吗？')) return;

            try {
                await fetch(`${API_BASE}/api/aliases/import/stop`, {
                    method: 'POST'
                });
            } catch (e) {
                console.error('停止导入失败:', e);
            }
        });
    }

    // 添加别名弹窗
    const addAliasBtn = document.getElementById('add-alias-btn');
    const aliasModal = document.getElementById('alias-modal');
    const aliasModalClose = document.querySelector('#alias-modal .close');
    const cancelAliasBtn = document.getElementById('cancel-alias-btn');

    if (addAliasBtn) {
        addAliasBtn.addEventListener('click', () => {
            aliasModal?.classList.remove('hidden');
        });
    }
    if (aliasModalClose) {
        aliasModalClose.addEventListener('click', () => {
            aliasModal?.classList.add('hidden');
        });
    }
    if (cancelAliasBtn) {
        cancelAliasBtn.addEventListener('click', () => {
            aliasModal?.classList.add('hidden');
        });
    }

    // 提交添加别名表单
    const addAliasForm = document.getElementById('add-alias-form');
    if (addAliasForm) {
        addAliasForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const aliasType = document.getElementById('alias-type')?.value;
            const originalName = document.getElementById('alias-original')?.value;
            const aliasName = document.getElementById('alias-name')?.value;

            try {
                const response = await fetch(`${API_BASE}/api/aliases`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        alias_type: aliasType,
                        original_name: originalName,
                        alias: aliasName
                    })
                });
                const data = await response.json();

                if (data.success) {
                    showToast('添加成功', 'success');
                    aliasModal?.classList.add('hidden');
                    addAliasForm.reset();
                    loadAliases();
                } else {
                    showToast('添加失败: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('添加失败: ' + e, 'error');
            }
        });
    }

    // 保存/重置配置按钮
    const saveConfigBtn = document.getElementById('save-config-btn');
    if (saveConfigBtn) {
        saveConfigBtn.addEventListener('click', async () => {
            if (!await showConfirm('保存配置', '确定要保存配置吗？插件将应用新配置。')) return;
            await saveConfig();
        });
    }

    const resetConfigBtn = document.getElementById('reset-config-btn');
    if (resetConfigBtn) {
        resetConfigBtn.addEventListener('click', () => {
            resetConfig();
        });
    }

    // 文件上传相关
    const importBtn = document.getElementById('import-btn');
    const importModal = document.getElementById('import-modal');
    const cancelImportBtn = document.getElementById('cancel-import-btn');
    const startImportBtn = document.getElementById('start-import-btn');
    const fileInput = document.getElementById('file-input');
    const dropZone = document.getElementById('drop-zone');
    const fileList = document.getElementById('file-list');
    let selectedFiles = [];

    if (importBtn) {
        importBtn.addEventListener('click', () => {
            importModal?.classList.remove('hidden');
        });
    }

    if (cancelImportBtn) {
        cancelImportBtn.addEventListener('click', () => {
            importModal?.classList.add('hidden');
            selectedFiles = [];
            if (fileList) {
                fileList.innerHTML = '';
                fileList.classList.add('hidden');
            }
            if (fileInput) fileInput.value = '';
        });
    }

    if (dropZone) {
        dropZone.addEventListener('click', () => fileInput?.click());
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.style.backgroundColor = 'var(--dp-color-accent-soft)';
        });
        dropZone.addEventListener('dragleave', () => {
            dropZone.style.backgroundColor = '';
        });
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.style.backgroundColor = '';
            const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
            addFilesToList(files);
        });
    }

    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            const files = Array.from(e.target.files);
            addFilesToList(files);
        });
    }

    function addFilesToList(files) {
        selectedFiles = [...selectedFiles, ...files];
        if (fileList) {
            fileList.classList.remove('hidden');
            fileList.replaceChildren();
            selectedFiles.forEach((file, index) => {
                const row = document.createElement('div');
                row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:4px 8px;border-bottom:1px dotted #808080;font-family:var(--dp-typography-mono);font-size:12px;';

                const name = document.createElement('span');
                name.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
                name.textContent = file.name;

                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'retro-key retro-key-pink';
                btn.style.cssText = 'padding:1px 6px;font-size:11px;';
                btn.dataset.index = String(index);
                btn.textContent = '移除';
                btn.addEventListener('click', () => {
                    const idx = parseInt(btn.dataset.index);
                    selectedFiles.splice(idx, 1);
                    if (fileInput) fileInput.value = '';
                    addFilesToList([]);
                    if (selectedFiles.length === 0 && fileList) fileList.classList.add('hidden');
                });

                row.append(name, btn);
                fileList.appendChild(row);
            });
        }
    }

    if (startImportBtn) {
        startImportBtn.addEventListener('click', async () => {
            if (selectedFiles.length === 0) {
                showToast('请选择要导入的图片', 'warning');
                return;
            }

            startImportBtn.disabled = true;
            startImportBtn.textContent = '导入中...';

            let successCount = 0;
            let failCount = 0;

            for (const file of selectedFiles) {
                const formData = new FormData();
                formData.append('file', file);

                try {
                    const response = await fetch(`${API_BASE}/api/images/upload`, {
                        method: 'POST',
                        body: formData
                    });
                    const data = await response.json();

                    if (data.success) {
                        successCount++;
                    } else {
                        failCount++;
                    }
                } catch (e) {
                    failCount++;
                }
            }

            selectedFiles = [];
            if (fileList) {
                fileList.innerHTML = '';
                fileList.classList.add('hidden');
            }
            if (fileInput) fileInput.value = '';
            importModal?.classList.add('hidden');

            startImportBtn.disabled = false;
            startImportBtn.textContent = '开始导入';

            if (failCount === 0) {
                showToast(`成功导入 ${successCount} 张图片`, 'success');
            } else {
                showToast(`导入完成: ${successCount} 成功, ${failCount} 失败`, 'warning');
            }

            loadImages();
            refreshMonitorFacts();
        });
    }
}

async function setConfirmStatus(imageId, confirmed, advanceNext = false) {
    if (confirmBusy || !imageId) return;
    if (detailDirty) { showToast('请先保存角色与描述，再确认图片', 'warning'); return; }
    confirmBusy = true;
    try {
        const response = await fetch(`${API_BASE}/api/images/${imageId}/confirm`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirmed })
        });
        const data = await response.json();

        if (response.ok && data.success) {
            window._currentConfirmed = confirmed ? 1 : 0;
            showToast(confirmed ? `✓ 已确认归档 #${imageId}` : `已标记为待校对 #${imageId}`, confirmed ? 'success' : 'warning');

            // 原地更新本地缓存与卡片徽章，保持当前滚动位置不回弹
            const item = currentLoadedImages.find(x => x.id === imageId);
            if (item) item.confirmed = confirmed ? 1 : 0;

            if ((currentFilter === 'confirmed' && !confirmed) || (currentFilter === 'unconfirmed' && confirmed)) {
                currentLoadedImages = currentLoadedImages.filter(x => x.id !== imageId);
                const removedCard = imageGrid.querySelector(`.image-card[data-id="${imageId}"]`);
                if (removedCard) removedCard.remove();
                totalImages = Math.max(0, totalImages - 1);
            } else {
                const badgeEl = imageGrid.querySelector(`.image-card[data-id="${imageId}"] .confirm-badge`);
                if (badgeEl) {
                    badgeEl.className = `confirm-badge ${confirmed ? 'confirmed' : 'unconfirmed'}`;
                    badgeEl.textContent = confirmed ? '✓ 已确认' : '待校对';
                }
            }

            if (advanceNext) {
                const nextPending = currentLoadedImages.find(x => !x.confirmed && x.id !== imageId);
                if (nextPending) {
                    currentImageId = nextPending.id;
                } else if (currentLoadedImages.length > 0 && !currentLoadedImages.some(x => x.id === currentImageId)) {
                    currentImageId = currentLoadedImages[0].id;
                }
            }

            if (currentImageId && currentLoadedImages.some(x => x.id === currentImageId)) {
                await openDetail(currentImageId);
            } else if (currentLoadedImages.length === 0) {
                await loadImages(false);
            }
            updatePagination();
            updateScrollSentinelUI();
            refreshMonitorFacts();
        } else {
            showToast('操作失败: ' + data.error, 'error');
        }
    } catch (e) {
        showToast('操作失败: ' + e, 'error');
    } finally { confirmBusy = false; }
}

function scrollLogsToBottom() {
    const output = document.getElementById('log-output');
    if (output) {
        output.scrollTop = output.scrollHeight;
    }
}

async function loadLogs(reset = false) {
    const output = document.getElementById('log-output');
    if (!output) return;

    if (reset) {
        logCursor = 0;
        output.textContent = '';
    }

    const params = new URLSearchParams();
    params.append('limit', reset ? '300' : '200');
    if (logCursor > 0) {
        params.append('since', String(logCursor));
    }

    try {
        const response = await fetch(`${API_BASE}/api/logs?${params}`);
        const data = await response.json();
        if (!data.success) return;

        const logs = Array.isArray(data.logs) ? data.logs : [];
        if (logs.length > 0) {
            const appended = logs.map(item => item.line).join('\n');
            output.textContent += output.textContent ? `\n${appended}` : appended;
            const lines = output.textContent.split('\n');
            if (lines.length > MAX_LOG_LINES) {
                output.textContent = lines.slice(-MAX_LOG_LINES).join('\n');
            }
        }
        logCursor = data.next || logCursor;

        const autoScroll = document.getElementById('log-auto-scroll');
        if (!autoScroll || autoScroll.checked) {
            scrollLogsToBottom();
        }
    } catch (e) {
        console.error('加载日志失败:', e);
    }
}

function startLogPolling(reset = false) {
    stopLogPolling();
    loadLogs(reset);
    logPollTimer = setInterval(() => loadLogs(false), 2000);
}

function stopLogPolling() {
    if (logPollTimer) {
        clearInterval(logPollTimer);
        logPollTimer = null;
    }
}

// 检查登录状态
async function checkAuth() {
    try {
        const response = await fetch(`${API_BASE}/api/auth/info`);
        const data = await response.json();
        if (data.success && data.logged_in) {
            showMainPage();
            await cleanupMissingFiles();
            await refreshMonitorFacts();
            await loadImages();
        } else {
            showLoginPage();
        }
    } catch (e) {
        console.error('Auth check error:', e);
        showLoginPage();
    }
}

async function refreshMonitorFacts() {
    try {
        const response = await fetch(`${API_BASE}/api/stats?days=7`);
        const data = await response.json();
        if (data && data.success) {
            const tot = Number(data.total || 0);
            const conf = Number(data.confirmed || 0);
            const unconf = Number(data.unconfirmed || 0);
            const mTot = document.getElementById('monitor-total');
            const mConf = document.getElementById('monitor-confirmed');
            const mUnconf = document.getElementById('monitor-unconfirmed');
            if (mTot) mTot.textContent = tot.toLocaleString();
            if (mConf) mConf.textContent = conf.toLocaleString();
            if (mUnconf) mUnconf.textContent = unconf.toLocaleString();

            const segBar = document.getElementById('monitor-segmented-bar');
            if (segBar && tot > 0) {
                const filledCount = Math.max(0, Math.min(12, Math.round((conf / tot) * 12)));
                segBar.innerHTML = '';
                for (let i = 0; i < 12; i++) {
                    const span = document.createElement('span');
                    span.className = `seg-block ${i < filledCount ? 'filled-teal' : 'filled-yellow'}`;
                    segBar.appendChild(span);
                }
            }
        }
    } catch (e) {
        // Ignore if offline or unauthenticated
    }
}

// 页面加载时清理无效记录
async function cleanupMissingFiles() {
    try {
        await fetch(`${API_BASE}/api/maintenance/cleanup`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'db' })
        });
    } catch (e) {
        console.error('清理失败:', e);
    }
}

async function loadImages(append = false) {
    if (!append) {
        if (!await allowDiscard()) return;
        detailDirty = false;
        currentPage = 0;
    } else {
        if (isLoadingMore || !hasMoreImages) return;
    }

    const requestRevision = append ? listRevision : ++listRevision;
    if (!append) {
        detailRevision++;
        setInspectorEnabled(false);
    }

    isLoadingMore = true;
    updateScrollSentinelUI();

    pageSize = calculatePageSize();
    const offset = append ? currentLoadedImages.length : 0;
    const params = new URLSearchParams();

    if (currentFilter === 'confirmed') {
        params.append('confirmed', '1');
    } else if (currentFilter === 'unconfirmed') {
        params.append('confirmed', '0');
    }

    params.append('limit', pageSize);
    params.append('offset', offset);

    let url;
    if (isSearchMode && currentSearchKeyword) {
        params.append('keyword', currentSearchKeyword);
        url = `${API_BASE}/api/images/search?${params}`;
    } else {
        url = `${API_BASE}/api/images?${params}`;
    }

    try {
        const response = await fetch(url);
        const data = await response.json();
        if (requestRevision !== listRevision) return;
        if (!response.ok || !data.success) throw new Error(data.error || '加载失败');
        if (data.success) {
            totalImages = data.total;
            const fetched = data.images || [];
            if (append) {
                const existingIds = new Set(currentLoadedImages.map(x => x.id));
                const uniqueNew = fetched.filter(x => !existingIds.has(x.id));
                currentLoadedImages = currentLoadedImages.concat(uniqueNew);
                renderImages(uniqueNew, true);
                currentPage = Math.floor(currentLoadedImages.length / pageSize);
                if (fetched.length === 0) {
                    hasMoreImages = false;
                }
            } else {
                currentLoadedImages = fetched;
                renderImages(currentLoadedImages, false);
                if (!currentLoadedImages.length) clearInspector();
                if (currentLoadedImages.length > 0) {
                    const stillExists = currentLoadedImages.some(x => x.id === currentImageId);
                    if (!currentImageId || !stillExists) {
                        await openDetail(currentLoadedImages[0].id);
                    } else {
                        await openDetail(currentImageId);
                    }
                }
            }
            updatePagination();
        }
    } catch (e) {
        showToast('加载图片失败，请重试: ' + e.message, 'error');
    } finally {
        isLoadingMore = false;
        updateScrollSentinelUI();
    }
}

// 搜索图片（支持别名匹配）
async function searchImagesWithAlias(keyword) {
    currentSearchKeyword = keyword;
    isSearchMode = true;
    currentPage = 0;
    await loadImages();
    if (totalImages > 0) {
        showToast(`找到 ${totalImages} 张相关图片`, 'info');
    } else {
        showToast('未找到相关图片', 'warning');
    }
}

let selectedImages = new Set();
let batchMode = false;
let batchBusy = false;

// 渲染图片列表 (支持无限滚动追加 & 毛玻璃环境色晕染)
function renderImages(images, append = false) {
    if (!append) {
        imageGrid.innerHTML = '';
        const loadedIds = new Set(images.map(x => x.id));
        selectedImages.forEach(id => { if (!loadedIds.has(id)) selectedImages.delete(id); });
        updateBatchOperationsUI();
    }

    if (!append && images.length === 0) {
        imageGrid.innerHTML = `
            <div style="grid-column: 1 / -1; padding: 48px 16px; text-align: center; font-family: var(--dp-typography-mono); font-weight: 700;">
                [EMPTY_SET] 当前筛选条件下暂无原画记录
            </div>
        `;
        return;
    }

    images.forEach(img => {
        const thumbUrl = `${API_BASE}/images/${encodeURIComponent(String(img.file_name || ''))}?size=thumb`;
        const card = document.createElement('div');
        card.className = `image-card ${img.id === currentImageId ? 'active-cel' : ''}`;
        card.dataset.filename = img.file_name;
        card.dataset.id = String(img.id);
        card.tabIndex = 0;
        card.setAttribute('aria-label', `查看图片 ${img.id} 的详情`);
        card.addEventListener('keydown', e => {
            if (e.target !== card || e.key !== 'Enter') return;
            e.preventDefault();
            batchMode ? toggleBatchSelection(img.id) : openDetail(img.id);
        });

        let tagsText = '';
        if (img.tags) {
            const allTags = Object.values(img.tags).flat();
            tagsText = allTags.slice(0, 3).join(' · ');
        }

        const characterText = formatCharacterText(img.character);

        const titleBar = document.createElement('div');
        titleBar.className = 'cel-window-bar';
        const cutSpan = document.createElement('span');
        cutSpan.textContent = `#${img.id}`;
        const selMark = document.createElement('span');
        selMark.className = 'batch-select-mark';
        selMark.setAttribute('aria-hidden', 'true');
        selMark.textContent = '✓';
        titleBar.append(cutSpan, selMark);
        if (selectedImages.has(img.id)) card.classList.add('batch-selected');

        // 图片毛玻璃画框井（底层高斯模糊环境色散射 + 上层高清缩略图）
        const imageWrap = document.createElement('div');
        imageWrap.className = 'cel-picture-well';
        const ambientImg = document.createElement('img');
        ambientImg.className = 'cel-ambient-backdrop';
        ambientImg.src = thumbUrl;
        ambientImg.alt = '';
        ambientImg.setAttribute('aria-hidden', 'true');
        ambientImg.loading = 'lazy';
        const image = document.createElement('img');
        image.className = 'cel-main-img';
        image.src = thumbUrl;
        image.alt = String(characterText || img.file_name || '');
        image.loading = 'lazy';
        imageWrap.append(ambientImg, image);

        // 底部白色内凹信息签条
        const metaWell = document.createElement('div');
        metaWell.className = 'cel-meta-well';

        const charLine = document.createElement('div');
        charLine.className = 'cel-char-line';
        const character = document.createElement('div');
        character.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;';
        character.title = characterText;
        character.textContent = String(characterText || '未知角色');

        const badge = document.createElement('button');
        badge.type = 'button';
        badge.className = `confirm-badge ${img.confirmed ? 'confirmed' : 'unconfirmed'}`;
        badge.title = img.confirmed ? '点击切换为待校对' : '点击一键盖章归档';
        badge.textContent = img.confirmed ? '✓ 已确认' : '待校对';
        badge.addEventListener('click', (e) => {
            e.stopPropagation();
            if (batchMode) { toggleBatchSelection(img.id); return; }
            const item = currentLoadedImages.find(x => x.id === img.id) || img;
            setConfirmStatus(img.id, !item.confirmed, false);
        });
        charLine.append(character, badge);

        const tagLine = document.createElement('div');
        tagLine.className = 'cel-tag-line';
        const tags = document.createElement('span');
        tags.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;';
        tags.textContent = String(tagsText || '无标签');
        tagLine.appendChild(tags);

        metaWell.append(charLine, tagLine);
        card.append(titleBar, imageWrap, metaWell);

        card.addEventListener('dblclick', (e) => {
            if (batchMode || e.target.closest('button')) return;
            openZoom(img.file_name);
        });

        card.addEventListener('click', (e) => {
            if (e.target.closest('button,input')) return;
            if (batchMode) {
                toggleBatchSelection(img.id);
                return;
            }
            document.querySelectorAll('.image-card').forEach(c => {
                c.classList.toggle('active-cel', Number(c.dataset.id) === img.id);
            });
            openDetail(img.id).then(() => {
                if (window.innerWidth <= 760 && currentImageId === img.id) document.querySelector('.inspector-window').scrollIntoView({block:'start'});
            });
        });

        imageGrid.appendChild(card);
    });
    if (batchMode && append) updateBatchOperationsUI();
}

function formatCharacterText(raw) {
    if (!raw) return '未知角色';
    try {
        const chars = typeof raw === 'string' ? JSON.parse(raw) : raw;
        if (Array.isArray(chars)) {
            return chars.length ? chars.map(c => c.work ? `${c.name} [${c.work}]` : c.name).join(', ') : '未知角色';
        }
    } catch (_) {}
    return String(raw);
}

function updateCardCharacter(id, character) {
    const item = currentLoadedImages.find(x => x.id === id);
    if (item) item.character = character;
    const el = imageGrid.querySelector(`.image-card[data-id="${id}"] .cel-char-line > div`);
    if (el) {
        el.textContent = formatCharacterText(character);
        el.title = el.textContent;
    }
}

function openZoom(fileName) {
    const zoomImg = document.getElementById('zoom-modal-image');
    if (!zoomImg || !detailModal || !fileName) return;
    zoomImg.src = `${API_BASE}/images/${encodeURIComponent(String(fileName))}`;
    detailModal.classList.remove('hidden');
    detailModal.querySelector('.close')?.focus();
}

async function setBatchMode(on) {
    if (on && !await allowDiscard()) return;
    batchMode = on;
    if (on) detailDirty = false;
    selectedImages.clear();
    imageGrid.querySelectorAll('.image-card.batch-selected').forEach(c => c.classList.remove('batch-selected'));
    document.getElementById('tab-images')?.classList.toggle('batch-mode', on);
    const btn = document.getElementById('batch-mode-btn');
    if (btn) {
        btn.textContent = on ? '✕ 退出批量选择' : '☐ 批量选择';
        btn.setAttribute('aria-pressed', String(on));
        btn.classList.toggle('retro-key-primary', on);
    }
    const hint = document.getElementById('grid-status-hint');
    if (hint) hint.dataset.batch = on ? '1' : '';
    updateBatchOperationsUI();
    if (!on && currentImageId) openDetail(currentImageId);
}

function toggleBatchSelection(id) {
    if (selectedImages.has(id)) selectedImages.delete(id); else selectedImages.add(id);
    imageGrid.querySelector(`.image-card[data-id="${id}"]`)?.classList.toggle('batch-selected', selectedImages.has(id));
    updateBatchOperationsUI();
}

function updateBatchOperationsUI() {
    const batchOps = document.getElementById('batch-operations');
    const panel = document.getElementById('batch-panel');
    const single = document.getElementById('inspector-single');
    const n = selectedImages.size;

    batchOps?.classList.toggle('hidden', !batchMode);
    panel?.classList.toggle('hidden', !batchMode);
    single?.classList.toggle('hidden', batchMode);
    if (!batchMode) return;

    const loadedCount = imageGrid.querySelectorAll('.image-card').length;
    const countText = `已选择 ${n} 张图片`;
    const selectedCount = document.getElementById('selected-count');
    if (selectedCount) selectedCount.textContent = countText;
    const selectAllBtn = document.getElementById('select-all-btn');
    if (selectAllBtn) selectAllBtn.textContent = loadedCount > 0 && n >= loadedCount ? '取消全选' : '全选已加载';

    const title = document.getElementById('batch-panel-count');
    if (title) title.textContent = n ? `${n} 张` : '未选择';
    const empty = document.getElementById('batch-panel-empty');
    const body = document.getElementById('batch-panel-body');
    empty?.classList.toggle('hidden', n > 0);
    body?.classList.toggle('hidden', n === 0);

    document.querySelectorAll('[data-batch-action]').forEach(b => {
        const label = b.dataset.label || b.textContent;
        b.dataset.label = label;
        b.textContent = n > 1 ? `${label} ×${n}` : label;
        b.disabled = n === 0 || batchBusy;
    });

    const strip = document.getElementById('batch-thumb-strip');
    if (strip) {
        strip.replaceChildren();
        const ids = Array.from(selectedImages);
        ids.slice(0, 24).forEach(id => {
            const item = currentLoadedImages.find(x => x.id === id);
            if (!item) return;
            const cell = document.createElement('button');
            cell.type = 'button';
            cell.className = 'batch-thumb';
            cell.title = `#${id} · 点击移出选择`;
            const im = document.createElement('img');
            im.src = `${API_BASE}/images/${encodeURIComponent(String(item.file_name || ''))}?size=thumb`;
            im.alt = `#${id}`;
            im.loading = 'lazy';
            cell.appendChild(im);
            cell.addEventListener('click', () => toggleBatchSelection(id));
            strip.appendChild(cell);
        });
        if (ids.length > 24) {
            const more = document.createElement('span');
            more.className = 'batch-thumb batch-thumb-more';
            more.textContent = `+${ids.length - 24}`;
            strip.appendChild(more);
        }
    }

    const stats = document.getElementById('batch-panel-stats');
    if (stats) {
        const items = currentLoadedImages.filter(x => selectedImages.has(x.id));
        const conf = items.filter(x => x.confirmed).length;
        stats.textContent = `已确认 ${conf} · 待校对 ${items.length - conf}`;
    }
}

async function runBatchPerImage(ids, label, endpoint) {
    const progress = showToast(`${label}中 0 / ${ids.length}`, 'info', { persistent: true });
    let ok = 0, fail = 0;
    for (const id of ids) {
        try {
            const res = await fetch(`${API_BASE}/api/images/${id}/${endpoint}`, { method: 'POST' });
            const data = await res.json();
            if (res.ok && data.success) ok++; else fail++;
        } catch (_) { fail++; }
        progress.update(`${label}中 ${ok + fail} / ${ids.length}`);
    }
    progress.close();
    showToast(fail ? `${label}完成：${ok} 成功，${fail} 失败` : `${label}完成：共 ${ok} 张`, fail ? 'warning' : 'success');
}

async function handleBatchAction(action) {
    const ids = Array.from(selectedImages);
    if (!ids.length || batchBusy) return;
    const n = ids.length;
    const confirmText = {
        confirm: ['批量确认', `确定要确认选中的 ${n} 张图片吗？`],
        unconfirm: ['取消确认', `确定要取消确认选中的 ${n} 张图片吗？`],
        recognize: ['批量识别角色', `将逐张识别 ${n} 张图片的角色（AnimeTrace，失败回退 VLM），可能需要较长时间。继续？`],
        reanalyze: ['批量 VLM 重分析', `将逐张重新分析 ${n} 张图片的标签、角色与描述，可能需要较长时间。继续？`],
        delete: ['批量删除', `确定要删除选中的 ${n} 张图片吗？此操作不可恢复！`],
    }[action];
    if (!confirmText || !await showConfirm(...confirmText)) return;

    batchBusy = true;
    updateBatchOperationsUI();
    try {
        if (action === 'confirm' || action === 'unconfirm') {
            const res = await fetch(`${API_BASE}/api/images/batch/confirm`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image_ids: ids, confirmed: action === 'confirm' })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            showToast(data.message, 'success');
        } else if (action === 'delete') {
            const res = await fetch(`${API_BASE}/api/images/batch`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image_ids: ids })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);
            showToast(data.message, 'success');
            if (ids.includes(currentImageId)) currentImageId = null;
        } else if (action === 'recognize') {
            await runBatchPerImage(ids, '识别角色', 'recognize_character');
        } else if (action === 'reanalyze') {
            await runBatchPerImage(ids, 'VLM 重分析', 'reanalyze');
        }
        selectedImages.clear();
        await loadImages();
        refreshMonitorFacts();
    } catch (e) {
        showToast('操作失败: ' + (e.message || e), 'error');
    } finally {
        batchBusy = false;
        updateBatchOperationsUI();
    }
}

function bindBatchControls() {
    document.getElementById('batch-mode-btn')?.addEventListener('click', () => setBatchMode(!batchMode));
    document.getElementById('select-all-btn')?.addEventListener('click', () => {
        const cards = imageGrid.querySelectorAll('.image-card');
        const selectAll = selectedImages.size < cards.length;
        cards.forEach(c => {
            const id = Number(c.dataset.id);
            if (selectAll) selectedImages.add(id); else selectedImages.delete(id);
            c.classList.toggle('batch-selected', selectAll);
        });
        updateBatchOperationsUI();
    });
    document.getElementById('batch-clear-btn')?.addEventListener('click', () => {
        selectedImages.clear();
        imageGrid.querySelectorAll('.image-card.batch-selected').forEach(c => c.classList.remove('batch-selected'));
        updateBatchOperationsUI();
    });
    document.querySelectorAll('[data-batch-action]').forEach(b => {
        b.addEventListener('click', () => handleBatchAction(b.dataset.batchAction));
    });
}

// 更新分页信息
function updatePagination() {
    const totalPages = Math.ceil(totalImages / pageSize) || 1;
    document.getElementById('total-pages').textContent = totalPages;
    document.getElementById('image-count').textContent = `共 ${totalImages} 张图片`;
    document.getElementById('page-input').value = currentPage + 1;
    document.getElementById('page-input').max = totalPages;

    document.getElementById('first-page').disabled = currentPage === 0;
    document.getElementById('prev-page').disabled = currentPage === 0;
    document.getElementById('next-page').disabled = currentPage >= totalPages - 1;
    document.getElementById('last-page').disabled = currentPage >= totalPages - 1;
}

// 加载统计信息 (GitHub Contributions Calendar Heatmap)
let statsChart = null;

async function loadStats() {
    const days = parseInt(document.getElementById('stats-days')?.value || '365');

    try {
        const response = await fetch(`${API_BASE}/api/stats?days=${days}`);
        const data = await response.json();

        if (data.success) {
            document.getElementById('stats-total').textContent = (data.total || 0).toLocaleString();
            document.getElementById('stats-confirmed').textContent = (data.confirmed || 0).toLocaleString();
            document.getElementById('stats-unconfirmed').textContent = (data.unconfirmed || 0).toLocaleString();
            document.getElementById('stats-today').textContent = (data.today_new || 0).toLocaleString();

            let dailyList = data.daily || [];
            if (days > 30 && dailyList.length < days) {
                try {
                    const cacheRes = await fetch(`${API_BASE}/web/stats_365.json?t=${Date.now()}`);
                    if (cacheRes.ok) {
                        const cacheJson = await cacheRes.json();
                        if (Array.isArray(cacheJson.daily) && cacheJson.daily.length >= days) {
                            const mergedMap = new Map(cacheJson.daily.map(x => [x.date || x.label, x]));
                            dailyList.forEach(x => mergedMap.set(x.date || x.label, x));
                            dailyList = Array.from(mergedMap.values()).slice(-days);
                        }
                    }
                } catch (_) {
                    // Ignore cache fetch errors
                }
            }

            updateStatsChart(dailyList, days);
        }
    } catch (e) {
        console.error('加载统计失败:', e);
    }
}

function getContributionLevel(count, maxCount) {
    if (!count || count <= 0) return 0;
    const refMax = Math.max(4, maxCount);
    const ratio = count / refMax;
    if (ratio <= 0.25) return 1;
    if (ratio <= 0.5) return 2;
    if (ratio <= 0.75) return 3;
    return 4;
}

// 渲染 GitHub 贡献日历热力图
function updateStatsChart(dailyData, days = 365) {
    const container = document.getElementById('gh-contrib-graph');
    if (!container) return;
    container.replaceChildren();

    const now = new Date();
    const mapByDate = new Map();
    dailyData.forEach(item => {
        if (item.date) {
            mapByDate.set(item.date, Number(item.count || 0));
        } else if (item.label) {
            mapByDate.set(item.label, Number(item.count || 0));
        }
    });

    const totalDays = Math.max(30, Number(days) || 365);
    const entries = [];
    for (let i = totalDays - 1; i >= 0; i--) {
        const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
        const yyyy = d.getFullYear();
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        const dateStr = `${yyyy}-${mm}-${dd}`;
        const slashLabel = `${mm}/${dd}`;
        const dashLabel = `${mm}-${dd}`;
        const count = mapByDate.has(dateStr)
            ? mapByDate.get(dateStr)
            : (mapByDate.get(slashLabel) ?? mapByDate.get(dashLabel) ?? 0);
        entries.push({ dateObj: d, dateStr, month: d.getMonth(), weekday: d.getDay(), count });
    }

    const totalPeriodCount = entries.reduce((acc, x) => acc + x.count, 0);
    const activeDays = entries.filter(x => x.count > 0).length;
    const maxSingleDay = entries.reduce((m, x) => Math.max(m, x.count), 0);

    const summaryEl = document.getElementById('gh-contrib-summary');
    if (summaryEl) {
        summaryEl.textContent = `最近 ${totalDays} 天共收录 ${totalPeriodCount.toLocaleString()} 张图片`;
    }
    const streaksEl = document.getElementById('gh-contrib-streaks');
    if (streaksEl) {
        streaksEl.innerHTML = `
            <span>活跃天数 <strong>${activeDays}</strong> 天</span>
            <span>单日最高 <strong>${maxSingleDay}</strong> 张</span>
        `;
    }

    // Pad leading empty days so column 0 starts on Sunday (weekday 0)
    const firstWeekday = entries[0]?.weekday || 0;
    const padded = [];
    for (let p = 0; p < firstWeekday; p++) {
        padded.push(null);
    }
    entries.forEach(e => padded.push(e));

    const weeks = [];
    for (let i = 0; i < padded.length; i += 7) {
        weeks.push(padded.slice(i, i + 7));
    }
    container.style.setProperty('--gh-weeks', String(weeks.length));

    const monthNames = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'];
    const monthsRow = document.createElement('div');
    monthsRow.className = 'gh-months-row';
    let lastMonth = -1;
    weeks.forEach((week, wIdx) => {
        const span = document.createElement('span');
        const firstReal = week.find(Boolean);
        if (firstReal && firstReal.month !== lastMonth && (wIdx === 0 || firstReal.dateObj.getDate() <= 7)) {
            span.textContent = monthNames[firstReal.month];
            lastMonth = firstReal.month;
        }
        monthsRow.appendChild(span);
    });

    const bodyRow = document.createElement('div');
    bodyRow.className = 'gh-body-row';

    const weekdaysCol = document.createElement('div');
    weekdaysCol.className = 'gh-weekdays-col';
    ['', '周一', '', '周三', '', '周五', ''].forEach(label => {
        const s = document.createElement('span');
        s.textContent = label;
        weekdaysCol.appendChild(s);
    });

    const weeksGrid = document.createElement('div');
    weeksGrid.className = 'gh-weeks-grid';
    const selectedDayEl = document.getElementById('gh-contrib-selected-day');

    weeks.forEach(week => {
        const col = document.createElement('div');
        col.className = 'gh-week-col';
        for (let dIdx = 0; dIdx < 7; dIdx++) {
            const cellData = week[dIdx];
            const cell = document.createElement('span');
            if (!cellData) {
                cell.className = 'gh-cell gh-empty';
            } else {
                const lvl = getContributionLevel(cellData.count, maxSingleDay);
                cell.className = `gh-cell gh-level-${lvl}`;
                const tip = `${cellData.dateStr}：新增收录 ${cellData.count} 张图片`;
                cell.title = tip;
                cell.setAttribute('aria-label', tip);
                const showDetail = () => {
                    if (selectedDayEl) {
                        selectedDayEl.textContent = tip;
                    }
                };
                cell.addEventListener('mouseenter', showDetail);
                cell.addEventListener('click', showDetail);
            }
            col.appendChild(cell);
        }
        weeksGrid.appendChild(col);
    });

    bodyRow.append(weekdaysCol, weeksGrid);
    container.append(monthsRow, bodyRow);
}

// 插件配置分类定义：左侧显示对应配置项，右侧显示类名导航
const CONFIG_CATEGORIES = [
    {
        id: 'collection',
        name: '群聊收图与回复',
        desc: '控制白名单群号、最小入库尺寸及重复图片提示',
        keys: ['allowed_groups', 'min_image_width', 'min_image_height', 'duplicate_reply_probability', 'duplicate_reply_messages']
    },
    {
        id: 'ai_vision',
        name: 'AI 视觉与筛选模型',
        desc: '配置 VLM 识图开关、筛选提示词与 JEV System One 判定',
        keys: ['enable_llm_filter', 'enable_llm_content', 'llm_provider_id', 'filter_prompt', 'jev_filter_enabled', 'jev_filter_api_key', 'jev_filter_api_base', 'jev_filter_model', 'jev_filter_threshold']
    },
    {
        id: 'storage_perf',
        name: '压缩与缩略图缓存',
        desc: '控制下载大小上限、图片压缩质量与缩略图缓存策略',
        keys: ['max_file_size_mb', 'max_download_size_mb', 'max_image_pixels', 'max_image_dimension', 'jpeg_quality', 'thumbnail_size', 'thumbnail_cache_size', 'max_api_images']
    },
    {
        id: 'webui_security',
        name: 'WebUI 服务与访问安全',
        desc: '管理 WebUI 监听地址、端口、登录密码与跨域来源',
        keys: ['webui_enabled', 'webui_host', 'webui_port', 'webui_password', 'cors_origins']
    }
];

// 全局配置变量
let configSchema = null;
let originalConfig = null;

// 加载配置
async function loadConfig() {
    const configForm = document.getElementById('config-form');

    try {
        const [configRes, schemaRes] = await Promise.all([
            fetch(`${API_BASE}/api/config`),
            fetch(`${API_BASE}/api/config/schema`)
        ]);

        const configData = await configRes.json();
        const schemaData = await schemaRes.json();

        if (!configData.success || !schemaData.success) {
            const error = document.createElement('p');
            error.style.cssText = 'color:#921c30;background:#fff1f2;padding:8px;font-weight:700;';
            error.textContent = '加载配置失败';
            configForm.replaceChildren(error);
            return;
        }

        const filteredConfig = {};
        const filteredSchema = {};

        for (const [key, value] of Object.entries(configData)) {
            if (key !== 'success' && key !== 'message' && key !== 'error') {
                filteredConfig[key] = value;
            }
        }

        for (const [key, value] of Object.entries(schemaData)) {
            if (key !== 'success' && key !== 'message' && key !== 'error') {
                filteredSchema[key] = value;
            }
        }

        originalConfig = filteredConfig;
        configSchema = filteredSchema;

        renderConfigForm(filteredConfig, filteredSchema);
    } catch (e) {
        console.error('加载配置失败:', e);
        const error = document.createElement('p');
        error.style.cssText = 'color:#921c30;background:#fff1f2;padding:8px;font-weight:700;';
        error.textContent = `加载配置失败: ${e.message}`;
        configForm.replaceChildren(error);
    }
}

function createConfigItemElement(key, def, config) {
    const value = config[key] !== undefined ? config[key] : def.default;
    const description = def.description || '';
    const item = document.createElement('div');
    item.className = 'retro-window';
    item.style.padding = '12px';
    if (key === 'filter_prompt') {
        item.style.gridColumn = '1 / -1';
    }

    if (def.type === 'bool') {
        const wrapper = document.createElement('label');
        wrapper.style.cssText = 'display:flex;align-items:flex-start;gap:10px;cursor:pointer;';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.id = `config-${key}`;
        input.checked = Boolean(value);
        input.style.cssText = 'width:18px;height:18px;margin-top:2px;flex-shrink:0;accent-color:var(--dp-color-accent);';
        const text = document.createElement('div');
        const title = document.createElement('div');
        title.style.cssText = 'font-family:var(--dp-typography-mono);font-size:14px;font-weight:600;';
        title.textContent = key;
        const help = document.createElement('p');
        help.style.cssText = 'font-size:14px;margin-top:4px;';
        help.textContent = description;
        text.append(title, help);
        wrapper.append(input, text);
        item.appendChild(wrapper);
        return item;
    }

    const label = document.createElement('label');
    label.style.cssText = 'display:block;font-family:var(--dp-typography-mono);font-size:14px;font-weight:600;margin-bottom:4px;';
    label.htmlFor = `config-${key}`;
    label.textContent = key;
    const help = document.createElement('p');
    help.style.cssText = 'font-size:14px;margin-bottom:8px;';
    help.textContent = description;

    let input;
    if (key === 'filter_prompt') {
        input = document.createElement('textarea');
        input.rows = 5;
        input.className = 'retro-input';
        input.style.cssText = 'width:100%;resize:vertical;';
    } else {
        input = document.createElement('input');
        input.type = key === 'webui_password' ? 'password' : (def.type === 'int' ? 'number' : 'text');
        input.className = 'retro-input';
        input.style.cssText = 'width:100%;';
    }
    input.id = `config-${key}`;

    if (key === 'webui_password') {
        input.value = '';
        input.placeholder = config.webui_password_set ? '留空表示不修改密码' : '请输入至少8位的非默认密码';
    } else if (def.type === 'list') {
        input.value = Array.isArray(value) ? value.join(',') : '';
        input.placeholder = '用逗号分隔多个值';
    } else {
        input.value = value === undefined || value === null ? '' : String(value);
    }

    item.append(label, help, input);
    return item;
}

// 渲染分类配置表单（左侧配置项分组列表 + 右侧类名导航目录）
function renderConfigForm(config, schema) {
    const configForm = document.getElementById('config-form');
    const categoryNav = document.getElementById('config-category-nav');
    if (!configForm) return;
    configForm.replaceChildren();

    const assignedKeys = new Set();
    const groups = CONFIG_CATEGORIES.map(cat => {
        const matchedKeys = cat.keys.filter(k => Object.prototype.hasOwnProperty.call(schema, k));
        matchedKeys.forEach(k => assignedKeys.add(k));
        return { ...cat, matchedKeys };
    }).filter(g => g.matchedKeys.length > 0);

    const remainingKeys = Object.keys(schema).filter(k => !assignedKeys.has(k));
    if (remainingKeys.length > 0) {
        groups.push({
            id: 'other',
            name: '其他扩展配置',
            desc: '未归类的插件参数设置',
            matchedKeys: remainingKeys
        });
    }

    if (!groups.some(g => g.id === currentConfigCategory) && currentConfigCategory !== 'all') {
        currentConfigCategory = 'all';
    }

    // 渲染左侧各分类区块（保留全部 input DOM 节点，切换分类时仅控制显隐，确保未保存修改不丢失）
    groups.forEach(group => {
        const section = document.createElement('section');
        section.className = 'config-group-section';
        section.dataset.categoryId = group.id;
        if (currentConfigCategory !== 'all' && currentConfigCategory !== group.id) {
            section.classList.add('hidden');
        }

        const header = document.createElement('div');
        header.className = 'config-group-header';
        header.innerHTML = `
            <div>
                <h3 class="config-group-title">${escapeHtml(group.name)}</h3>
                <p class="config-group-desc">${escapeHtml(group.desc)}</p>
            </div>
            <span class="config-cat-count">${group.matchedKeys.length} 项</span>
        `;

        const grid = document.createElement('div');
        grid.className = 'config-group-grid';
        group.matchedKeys.forEach(key => {
            grid.appendChild(createConfigItemElement(key, schema[key], config));
        });

        section.append(header, grid);
        configForm.appendChild(section);
    });

    // 渲染右侧类名导航栏
    if (categoryNav) {
        categoryNav.replaceChildren();
        const heading = document.createElement('div');
        heading.className = 'config-cat-heading';
        heading.textContent = '配置分类目录';
        categoryNav.appendChild(heading);

        const allEntry = {
            id: 'all',
            name: '全部配置类别',
            matchedKeys: Object.keys(schema)
        };

        [allEntry, ...groups].forEach(cat => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = `config-cat-btn ${currentConfigCategory === cat.id ? 'active' : ''}`;
            btn.dataset.catId = cat.id;
            btn.innerHTML = `
                <span>${escapeHtml(cat.name)}</span>
                <span class="config-cat-count">${cat.matchedKeys.length}</span>
            `;
            btn.addEventListener('click', () => {
                currentConfigCategory = cat.id;
                categoryNav.querySelectorAll('.config-cat-btn').forEach(b => {
                    b.classList.toggle('active', b.dataset.catId === cat.id);
                });
                configForm.querySelectorAll('.config-group-section').forEach(sec => {
                    sec.classList.toggle('hidden', cat.id !== 'all' && sec.dataset.categoryId !== cat.id);
                });
            });
            categoryNav.appendChild(btn);
        });
    }
}

// 保存配置
async function saveConfig() {
    if (!configSchema) return;

    const newConfig = {};

    for (const [key, def] of Object.entries(configSchema)) {
        const input = document.getElementById(`config-${key}`);
        if (!input) continue;
        if (key === 'webui_password' && input.value === '') continue;

        if (def.type === 'bool') {
            newConfig[key] = input.checked;
        } else if (def.type === 'int') {
            const number = Number(input.value);
            if (input.value.trim() === '' || !Number.isInteger(number)) { showToast(`${key} 必须是整数`, 'error'); input.focus(); return; }
            newConfig[key] = number;
        } else if (def.type === 'list') {
            const listStr = input.value.trim();
            newConfig[key] = listStr ? listStr.split(',').map(s => s.trim()) : [];
        } else {
            newConfig[key] = input.value;
        }
    }

    try {
        const response = await fetch(`${API_BASE}/api/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(newConfig)
        });
        const data = await response.json();

        if (data.success) {
            showToast('配置已保存，页面将在3秒后刷新', 'success');
            setTimeout(() => {
                location.reload();
            }, 3000);
        } else {
            showToast('保存失败: ' + data.error, 'error');
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

// 重置配置
function resetConfig() {
    if (originalConfig && configSchema) {
        renderConfigForm(originalConfig, configSchema);
        showToast('配置已重置', 'info');
    }
}

// 点击大图弹窗外部关闭
async function handleDetailOverlayClick() {
    if (detailModal) {
        detailModal.classList.add('hidden');
    }
}

// 同步右侧常驻检片校对槽 (Inspector Dock)
async function openDetail(imageId) {
    if (imageId !== currentImageId && !await allowDiscard()) return;
    const revision = ++detailRevision;
    setInspectorEnabled(false);

    try {
        const response = await fetch(`${API_BASE}/api/images/${imageId}`);
        const data = await response.json();

        if (revision !== detailRevision) return;
        if (response.ok && data.success) {
            currentImageId = imageId;
            detailDirty = false;
            setInspectorEnabled(true);
            document.querySelectorAll('.image-card').forEach(card => card.classList.toggle('active-cel', Number(card.dataset.id) === imageId));
            const img = data.image;

            const detailImg = document.getElementById('detail-image');
            if (detailImg) {
                detailImg.src = `${API_BASE}/images/${encodeURIComponent(String(img.file_name || ''))}`;
            }
            const zoomImg = document.getElementById('zoom-modal-image');
            if (zoomImg) {
                zoomImg.src = `${API_BASE}/images/${encodeURIComponent(String(img.file_name || ''))}`;
            }

            const frameIdEl = document.getElementById('dock-frame-id');
            if (frameIdEl) frameIdEl.textContent = `#${img.id}`;

            document.getElementById('detail-filename').textContent = img.file_name;
            document.getElementById('detail-group').textContent = img.group_id;
            document.getElementById('detail-sender').textContent = img.sender_id;
            document.getElementById('detail-time').textContent = new Date(img.timestamp * 1000).toLocaleString();
            document.getElementById('detail-description').value = img.description || '';

            window._currentConfirmed = img.confirmed || 0;
            const dockStatus = document.getElementById('dock-confirm-status');
            if (dockStatus) {
                dockStatus.textContent = img.confirmed ? '✓ 已确认' : '待校对';
                dockStatus.removeAttribute('style');
            }

            renderCharacterEditor(img.character);

            const tagsContainer = document.getElementById('detail-tags');
            tagsContainer.innerHTML = '';
            if (img.tags) {
                Object.entries(img.tags).forEach(([category, tags]) => {
                    if (Array.isArray(tags)) {
                        tags.forEach(tag => {
                            const tagEl = document.createElement('span');
                            tagEl.className = 'retro-tag-chip';
                            tagEl.textContent = `${category.slice(0, 3).toUpperCase()}:${tag}`;
                            tagsContainer.appendChild(tagEl);
                        });
                    }
                });
            }
        }
    } catch (e) {
        showToast('加载详情失败，请重新选择图片', 'error');
    }
}

// 渲染角色编辑器
function renderCharacterEditor(characterJson) {
    const container = document.querySelector('.character-list');
    if (!container) return;
    container.innerHTML = '';

    let characters = [];
    if (characterJson) {
        try {
            characters = typeof characterJson === 'string' ? JSON.parse(characterJson) : characterJson;
            if (!Array.isArray(characters)) characters = [];
        } catch (e) {
            characters = [];
        }
    }

    if (characters.length === 0) {
        characters = [{ name: '', work: '' }];
    }

    characters.forEach((char) => {
        addCharacterRow(char.name, char.work);
    });

    const addBtn = document.getElementById('add-character-btn');
    if (addBtn) {
        addBtn.onclick = () => { addCharacterRow('', ''); detailDirty = true; };
    }
}

// 添加一行角色输入
function addCharacterRow(name = '', work = '') {
    const container = document.querySelector('.character-list');
    if (!container) return;
    const row = document.createElement('div');
    row.className = 'char-edit-row';
    row.style.cssText = 'display:grid;grid-template-columns:1fr 1fr auto;gap:4px;align-items:center;';
    row.innerHTML = `
        <input type="text" class="char-name retro-input" style="width:100%;font-size:12px;padding:4px 6px;" placeholder="角色名 (如: 辻倉朱比華)">
        <input type="text" class="work-input retro-input" style="width:100%;font-size:12px;padding:4px 6px;" placeholder="作品名 (如: anemoi)">
        <button type="button" class="remove-char-btn retro-key retro-key-pink" style="padding:3px 7px;font-size:11px;" aria-label="移除角色行">✕</button>
    `;
    row.querySelector('.char-name').setAttribute('aria-label', '角色名');
    row.querySelector('.work-input').setAttribute('aria-label', '作品名');
    row.querySelector('.char-name').value = String(name || '');
    row.querySelector('.work-input').value = String(work || '');

    row.querySelector('.remove-char-btn').onclick = () => {
        container.removeChild(row);
        detailDirty = true;
    };

    container.appendChild(row);
}

// 获取角色编辑器中的数据并转换为JSON
function getCharacterJson() {
    const characters = [];

    document.querySelectorAll('.character-list .char-edit-row').forEach(row => {
        const name = row.querySelector('.char-name')?.value?.trim() || '';
        const work = row.querySelector('.work-input')?.value?.trim() || '';
        if (name) {
            characters.push({ name, work });
        }
    });

    return JSON.stringify(characters);
}

// 页面切换
function showLoginPage() {
    loginPage.classList.remove('hidden');
    mainPage.classList.add('hidden');
    currentImageId = null;
    listRevision++;
    detailRevision++;
}

function showMainPage() {
    loginPage.classList.add('hidden');
    mainPage.classList.remove('hidden');
}

// 别名管理
let aliasCurrentPage = 1;
let aliasTotalPages = 1;
let aliasPageSize = 25;
let aliasTotal = 0;

async function loadAliases() {
    const search = document.getElementById('search-alias')?.value || '';
    const typeFilter = document.getElementById('alias-type-filter')?.value || '';
    aliasPageSize = parseInt(document.getElementById('alias-page-size')?.value || '25');

    const params = new URLSearchParams();
    if (search) params.append('search', search);
    if (typeFilter) params.append('type', typeFilter);
    params.append('page', aliasCurrentPage);
    params.append('page_size', aliasPageSize);

    try {
        const response = await fetch(`${API_BASE}/api/aliases?${params}`);
        const data = await response.json();

        if (data.success) {
            aliasTotal = data.total;
            aliasTotalPages = data.total_pages || 1;
            renderAliases(data.aliases || []);
            updateAliasPagination();
        }
    } catch (e) {
        console.error('加载别名失败:', e);
    }
}

function updateAliasPagination() {
    document.getElementById('alias-page-info').textContent =
        `PAGE ${aliasCurrentPage} / ${aliasTotalPages} (TOTAL ${aliasTotal})`;
    document.getElementById('alias-prev-page').disabled = aliasCurrentPage <= 1;
    document.getElementById('alias-next-page').disabled = aliasCurrentPage >= aliasTotalPages;
}

function renderAliases(aliases) {
    const aliasList = document.getElementById('alias-list');
    aliasList.innerHTML = '';

    if (aliases.length === 0) {
        aliasList.innerHTML = '<p style="text-align:center;padding:32px;font-family:var(--dp-typography-mono);font-weight:700;">[NO_ALIASES] 暂无别名记录</p>';
        return;
    }

    aliases.forEach(alias => {
        const item = document.createElement('div');
        item.className = 'alias-row';
        item.style.cssText = 'display:flex;align-items:center;gap:10px;padding:6px 10px;background:var(--dp-color-window);border:1px solid var(--dp-color-ink);';

        const isCharacter = alias.alias_type === 'character';
        const typeBadge = document.createElement('span');
        typeBadge.style.cssText = `font-family:var(--dp-typography-mono);font-size:11px;font-weight:700;padding:2px 6px;border:1px solid #000;background:${isCharacter ? '#eaf0fe' : '#edf3ff'};color:${isCharacter ? '#000' : '#fff'};`;
        typeBadge.textContent = isCharacter ? 'CHARACTER / 角色' : 'WORK / 作品';

        const origSpan = document.createElement('span');
        origSpan.style.cssText = 'flex:1;font-weight:700;';
        origSpan.textContent = String(alias.original_name || '');

        const arrowSpan = document.createElement('span');
        arrowSpan.style.cssText = 'font-family:var(--dp-typography-mono);font-weight:700;color:var(--dp-color-accent);';
        arrowSpan.textContent = '<==>';

        const valSpan = document.createElement('span');
        valSpan.style.cssText = 'flex:1;font-family:var(--dp-typography-mono);';
        valSpan.textContent = String(alias.alias || '');

        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'retro-key retro-key-pink';
        deleteButton.style.cssText = 'padding:2px 8px;font-size:11px;';
        deleteButton.dataset.id = String(alias.id);
        deleteButton.textContent = '✕ 删除';

        deleteButton.addEventListener('click', async (e) => {
            if (!await showConfirm('删除别名', '确定要删除这个别名吗？')) return;

            const aliasId = e.currentTarget.dataset.id;
            try {
                const response = await fetch(`${API_BASE}/api/aliases/${aliasId}`, {
                    method: 'DELETE'
                });
                const data = await response.json();

                if (data.success) {
                    showToast('删除成功', 'success');
                    loadAliases();
                } else {
                    showToast('删除失败: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('删除失败: ' + e, 'error');
            }
        });

        item.append(typeBadge, origSpan, arrowSpan, valSpan, deleteButton);
        aliasList.appendChild(item);
    });
}

let importPollInterval = null;

function startImportPoll() {
    if (importPollInterval) clearInterval(importPollInterval);

    importPollInterval = setInterval(async () => {
        try {
            const response = await fetch(`${API_BASE}/api/aliases/import/status`);
            const data = await response.json();

            if (data.success) {
                const progress = data.progress || 0;
                document.getElementById('progress-fill').style.width = progress + '%';
                document.getElementById('progress-text').textContent =
                    `导入中: ${data.imported} / ${data.total} (${progress}%)`;

                if (!data.running) {
                    clearInterval(importPollInterval);
                    importPollInterval = null;

                    document.getElementById('import-progress').classList.add('hidden');
                    document.getElementById('progress-fill').style.width = '0%';

                    const btn = document.getElementById('import-alias-btn');
                    btn.disabled = false;
                    btn.textContent = '导入 aliases.json';

                    showToast(`导入完成: 共导入 ${data.imported} 个别名`, 'success');
                    loadAliases();
                }
            }
        } catch (e) {
            console.error('获取进度失败:', e);
        }
    }, 500);
}
