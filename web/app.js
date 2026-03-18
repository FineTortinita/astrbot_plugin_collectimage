const API_BASE = '';

let currentPage = 0;
let pageSize = 20;
let totalImages = 0;
let currentImageId = null;
let currentFilter = 'all';
let isSearchMode = false;
let detailModal = null;
let loginPage, mainPage, loginForm, loginError, imageGrid, imageCount;

// Toast 通知函数
function showToast(message, type = 'success') {
    const styles = {
        success: { background: 'linear-gradient(135deg, #22C55E, #16A34A)', borderRadius: '12px' },
        error: { background: 'linear-gradient(135deg, #EF4444, #DC2626)', borderRadius: '12px' },
        warning: { background: 'linear-gradient(135deg, #F59E0B, #D97706)', borderRadius: '12px' },
        info: { background: 'linear-gradient(135deg, #3B82F6, #2563EB)', borderRadius: '12px' }
    };
    
    Toastify({
        text: message,
        duration: 3000,
        style: styles[type] || styles.success,
        close: true,
        gravity: 'bottom',
        position: 'right'
    }).showToast();
}

// 自定义确认弹窗
function showConfirm(title, message) {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirm-modal');
        const titleEl = document.getElementById('confirm-title');
        const messageEl = document.getElementById('confirm-message');
        const cancelBtn = document.getElementById('confirm-cancel');
        const okBtn = document.getElementById('confirm-ok');
        
        titleEl.textContent = title;
        messageEl.textContent = message;
        modal.classList.remove('hidden');
        
        const closeModal = (result) => {
            modal.classList.add('hidden');
            cancelBtn.removeEventListener('click', handleCancel);
            okBtn.removeEventListener('click', handleOk);
            resolve(result);
        };
        
        const handleCancel = () => closeModal(false);
        const handleOk = () => closeModal(true);
        
        cancelBtn.addEventListener('click', handleCancel);
        okBtn.addEventListener('click', handleOk);
    });
}

// 安全添加事件监听器
function safeAddEvent(selector, event, handler) {
    const el = typeof selector === 'string' ? document.querySelector(selector) : selector;
    if (el) {
        el.addEventListener(event, handler);
    }
}

// 安全获取元素
function safeGet(id) {
    return document.getElementById(id);
}

// 页面加载时检查登录状态
document.addEventListener('DOMContentLoaded', async () => {
    // 初始化 DOM 元素
    loginPage = document.getElementById('login-page');
    mainPage = document.getElementById('main-page');
    loginForm = document.getElementById('login-form');
    loginError = document.getElementById('login-error');
    imageGrid = document.getElementById('image-grid');
    imageCount = document.getElementById('image-count');
    detailModal = document.getElementById('detail-modal');
    
    console.log('DOM loaded, initializing...');
    
    // 绑定所有事件
    bindEventListeners();
    
    await checkAuth();
});

// 绑定所有事件监听器
function bindEventListeners() {
    // 登录表单提交
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const password = document.getElementById('password').value;
            console.log('Attempting login with password:', password ? '***' : 'empty');
            
            try {
                const response = await fetch(`${API_BASE}/api/auth/login`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password })
                });
                const data = await response.json();
                console.log('Login response:', data);
                
                if (data.success) {
                    showMainPage();
                    loadImages();
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
            showLoginPage();
        });
    }

    // 搜索
    const searchBtn = document.getElementById('search-btn');
    if (searchBtn) {
        searchBtn.addEventListener('click', () => {
            const keyword = document.getElementById('search-keyword')?.value || '';
            if (keyword) {
                searchImagesWithAlias(keyword);
            } else {
                currentPage = 0;
                loadImages();
            }
        });
    }

    // 清除搜索
    const clearSearchBtn = document.getElementById('clear-search-btn');
    if (clearSearchBtn) {
        clearSearchBtn.addEventListener('click', () => {
            const keywordInput = document.getElementById('search-keyword');
            if (keywordInput) keywordInput.value = '';
            currentPage = 0;
            isSearchMode = false;
            loadImages();
        });
    }

    // 搜索框回车搜索
    const keywordInput = document.getElementById('search-keyword');
    if (keywordInput) {
        keywordInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                const keyword = keywordInput.value || '';
                if (keyword) {
                    searchImagesWithAlias(keyword);
                } else {
                    currentPage = 0;
                    loadImages();
                }
            }
        });
    }

    // 侧边栏筛选
    document.querySelectorAll('.sidebar-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelectorAll('.sidebar-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            
            currentFilter = item.dataset.filter;
            isSearchMode = false; // 退出搜索模式
            
            // 隐藏所有 tab 内容
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.add('hidden');
            });
            
            if (currentFilter === 'stats') {
                // 显示统计
                document.getElementById('tab-stats')?.classList.remove('hidden');
                loadStats();
            } else {
                // 显示图片列表
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

    // 详情弹窗
    const detailCloseBtn = document.querySelector('#detail-modal .close');
    
    if (detailCloseBtn && detailModal) {
        detailCloseBtn.addEventListener('click', () => {
            detailModal.classList.add('hidden');
        });
    }

    // 保存详情
    const saveDetailBtn = document.getElementById('save-detail-btn');
    if (saveDetailBtn) {
        saveDetailBtn.addEventListener('click', async () => {
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
                    showToast('保存成功', 'success');
                    loadImages();
                } else {
                    showToast('保存失败: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('保存失败: ' + e, 'error');
            }
        });
    }

    // 确认按钮
    const confirmBtn = document.getElementById('confirm-btn');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', async () => {
            try {
                const response = await fetch(`${API_BASE}/api/images/${currentImageId}/confirm`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ confirmed: true })
                });
                const data = await response.json();
                
                if (data.success !== false) {
                    window._currentConfirmed = 1;
                    showToast('已标记为已确认', 'success');
                    loadImages();
                } else {
                    showToast('操作失败: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('操作失败: ' + e, 'error');
            }
        });
    }

    // 取消确认按钮
    const unconfirmBtn = document.getElementById('unconfirm-btn');
    if (unconfirmBtn) {
        unconfirmBtn.addEventListener('click', async () => {
            try {
                const response = await fetch(`${API_BASE}/api/images/${currentImageId}/confirm`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ confirmed: false })
                });
                const data = await response.json();
                
                if (data.success !== false) {
                    window._currentConfirmed = 0;
                    showToast('已标记为未确认', 'warning');
                    loadImages();
                } else {
                    showToast('操作失败: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('操作失败: ' + e, 'error');
            }
        });
    }

    // AI 重新分析
    const reanalyzeBtn = document.getElementById('reanalyze-btn');
    if (reanalyzeBtn) {
        reanalyzeBtn.addEventListener('click', async () => {
            if (!await showConfirm('重新分析', '确定要重新分析这张图片吗？')) return;
            
            reanalyzeBtn.disabled = true;
            reanalyzeBtn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 inline mr-1 animate-spin"></i>分析中...';
            lucide.createIcons();
            
            try {
                const response = await fetch(`${API_BASE}/api/images/${currentImageId}/reanalyze`, {
                    method: 'POST'
                });
                const data = await response.json();
                
                if (data.success) {
                    showToast('重新分析完成', 'success');
                    openDetail(currentImageId);
                    loadImages();
                } else {
                    showToast('重新分析失败: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('重新分析失败: ' + e, 'error');
            } finally {
                reanalyzeBtn.disabled = false;
                reanalyzeBtn.innerHTML = '<i data-lucide="refresh-cw" class="w-4 h-4 inline mr-1"></i>重新分析';
                lucide.createIcons();
            }
        });
    }

    // 识别角色
    const recognizeBtn = document.getElementById('recognize-btn');
    if (recognizeBtn) {
        recognizeBtn.addEventListener('click', async () => {
            if (!await showConfirm('识别角色', '确定要识别这张图片的角色吗？')) return;
            
            recognizeBtn.disabled = true;
            recognizeBtn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 inline mr-1 animate-spin"></i>识别中...';
            lucide.createIcons();
            
            try {
                const response = await fetch(`${API_BASE}/api/images/${currentImageId}/recognize_character`, {
                    method: 'POST'
                });
                const data = await response.json();
                
                if (data.success) {
                    showToast('角色识别完成', 'success');
                    openDetail(currentImageId);
                    loadImages();
                } else {
                    showToast('角色识别失败: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('角色识别失败: ' + e, 'error');
            } finally {
                recognizeBtn.disabled = false;
                recognizeBtn.innerHTML = '<i data-lucide="user-check" class="w-4 h-4 inline mr-1"></i>识别角色';
                lucide.createIcons();
            }
        });
    }

    // 删除图片
    const deleteBtn = document.getElementById('delete-btn');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', async () => {
            if (!await showConfirm('删除图片', '确定要删除这张图片吗？此操作不可恢复！')) return;
            
            try {
                const response = await fetch(`${API_BASE}/api/images/${currentImageId}`, {
                    method: 'DELETE'
                });
                const data = await response.json();
                
                if (data.success) {
                    showToast('删除成功', 'success');
                    if (detailModal) detailModal.classList.add('hidden');
                    loadImages();
                } else {
                    showToast('删除失败: ' + data.error, 'error');
                }
            } catch (e) {
                showToast('删除失败: ' + e, 'error');
            }
        });
    }

    // 标签切换
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.dataset.tab;
            
            document.querySelectorAll('.tab-btn').forEach(b => {
                b.classList.remove('active', 'bg-purple-100', 'text-purple-700');
                b.classList.add('hover:bg-white/50', 'text-gray-600');
            });
            btn.classList.add('active', 'bg-purple-100', 'text-purple-700');
            btn.classList.remove('hover:bg-white/50', 'text-gray-600');
            
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.add('hidden');
            });
            document.getElementById(`tab-${tabName}`)?.classList.remove('hidden');
            
            // 显示/隐藏侧边栏
            const sidebar = document.getElementById('sidebar');
            if (sidebar) {
                if (tabName === 'images') {
                    sidebar.classList.remove('hidden');
                } else {
                    sidebar.classList.add('hidden');
                }
            }
            
            if (tabName === 'aliases') {
                aliasCurrentPage = 1;
                loadAliases();
            } else if (tabName === 'images') {
                currentPage = 0;
                loadImages();
            } else if (tabName === 'stats') {
                loadStats();
            }
        });
    });

    // 别名分页
    const aliasPrevBtn = document.getElementById('alias-prev-page');
    const aliasNextBtn = document.getElementById('alias-next-page');
    const aliasPageSizeSelect = document.getElementById('alias-page-size');

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

    // 搜索别名
    const searchAliasBtn = document.getElementById('search-alias-btn');
    const searchAliasInput = document.getElementById('search-alias');
    const aliasTypeFilter = document.getElementById('alias-type-filter');

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
            importAliasBtn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 inline mr-1 animate-spin"></i>启动中...';
            lucide.createIcons();
            
            try {
                const response = await fetch(`${API_BASE}/api/aliases/import`, {
                    method: 'POST'
                });
                const data = await response.json();
                
                if (data.success) {
                    importAliasBtn.innerHTML = '<i data-lucide="loader-2" class="w-4 h-4 inline mr-1 animate-spin"></i>导入中...';
                    const progressEl = document.getElementById('import-progress');
                    if (progressEl) progressEl.classList.remove('hidden');
                    startImportPoll();
                } else {
                    showToast('导入失败: ' + data.error, 'error');
                    importAliasBtn.disabled = false;
                    importAliasBtn.innerHTML = '<i data-lucide="upload" class="w-4 h-4 inline mr-1"></i>导入';
                    lucide.createIcons();
                }
            } catch (e) {
                showToast('导入失败: ' + e, 'error');
                importAliasBtn.disabled = false;
                importAliasBtn.innerHTML = '<i data-lucide="upload" class="w-4 h-4 inline mr-1"></i>导入';
                lucide.createIcons();
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

    // 添加别名按钮
    const addAliasBtn = document.getElementById('add-alias-btn');
    if (addAliasBtn) {
        addAliasBtn.addEventListener('click', () => {
            document.getElementById('alias-modal')?.classList.remove('hidden');
        });
    }

    // 关闭添加别名弹窗
    const aliasModal = document.getElementById('alias-modal');
    const aliasModalClose = document.querySelector('#alias-modal .close');
    const cancelAliasBtn = document.getElementById('cancel-alias-btn');

    if (aliasModalClose) {
        aliasModalClose.addEventListener('click', () => {
            if (aliasModal) aliasModal.classList.add('hidden');
        });
    }

    if (cancelAliasBtn) {
        cancelAliasBtn.addEventListener('click', () => {
            if (aliasModal) aliasModal.classList.add('hidden');
        });
    }

    if (aliasModal) {
        aliasModal.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal-overlay')) {
                aliasModal.classList.add('hidden');
            }
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
                    if (aliasModal) aliasModal.classList.add('hidden');
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
}

// 检查登录状态
async function checkAuth() {
    console.log('Checking auth...');
    try {
        const response = await fetch(`${API_BASE}/api/auth/info`);
        const data = await response.json();
        console.log('Auth info:', data);
        if (data.success && data.logged_in) {
            showMainPage();
            await cleanupMissingFiles();
            loadImages();
        } else {
            showLoginPage();
        }
    } catch (e) {
        console.error('Auth check error:', e);
        showLoginPage();
    }
}

// 页面加载时清理无效记录
async function cleanupMissingFiles() {
    try {
        const response = await fetch(`${API_BASE}/api/maintenance/cleanup`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({type: 'db'})
        });
        const data = await response.json();
        if (data.success && data.cleaned > 0) {
            console.log(`[CollectImage] 已清理 ${data.cleaned} 条无效记录`);
        }
    } catch (e) {
        console.error('清理失败:', e);
    }
}

// 加载图片列表
async function loadImages() {
    const params = new URLSearchParams();
    
    // 侧边栏筛选
    if (currentFilter === 'confirmed') {
        params.append('confirmed', '1');
    } else if (currentFilter === 'unconfirmed') {
        params.append('confirmed', '0');
    }
    
    params.append('limit', pageSize);
    params.append('offset', currentPage * pageSize);

    try {
        const response = await fetch(`${API_BASE}/api/images?${params}`);
        const data = await response.json();
        
        if (data.success) {
            totalImages = data.total;
            renderImages(data.images);
            updatePagination();
        }
    } catch (e) {
        console.error('加载图片失败:', e);
    }
}

// 搜索图片（支持别名匹配）
async function searchImagesWithAlias(keyword) {
    const params = new URLSearchParams();
    params.append('keyword', keyword);
    params.append('limit', 50);
    
    // 侧边栏筛选
    if (currentFilter === 'confirmed') {
        params.append('confirmed', '1');
    } else if (currentFilter === 'unconfirmed') {
        params.append('confirmed', '0');
    }

    try {
        const response = await fetch(`${API_BASE}/api/images/search?${params}`);
        const data = await response.json();
        
        if (data.success) {
            isSearchMode = true;
            totalImages = data.total;
            currentPage = 0;
            renderImages(data.images);
            updatePagination();
            showToast(`找到 ${data.total} 张相关图片`, 'info');
        }
    } catch (e) {
        console.error('搜索图片失败:', e);
        showToast('搜索失败', 'error');
    }
}

// 渲染图片列表
function renderImages(images) {
    imageGrid.innerHTML = '';
    
    if (images.length === 0) {
        imageGrid.innerHTML = `
            <div class="col-span-full flex flex-col items-center justify-center py-16 text-gray-400">
                <i data-lucide="image-off" class="w-16 h-16 mb-4"></i>
                <p>暂无图片</p>
            </div>
        `;
        lucide.createIcons();
        return;
    }

    images.forEach(img => {
        const card = document.createElement('div');
        card.className = 'image-card glass-card rounded-xl overflow-hidden cursor-pointer';
        
        let tagsText = '';
        if (img.tags) {
            const allTags = Object.values(img.tags).flat();
            tagsText = allTags.slice(0, 3).join(', ');
        }
        
        let characterText = '未知角色';
        if (img.character) {
            try {
                const chars = JSON.parse(img.character);
                if (Array.isArray(chars) && chars.length > 0) {
                    characterText = chars.map(c => c.work ? `${c.name}[${c.work}]` : c.name).join(', ');
                } else {
                    characterText = img.character;
                }
            } catch {
                characterText = img.character;
            }
        }
        
        card.innerHTML = `
            <div class="aspect-square overflow-hidden bg-gray-100">
                <img src="${API_BASE}/images/${img.file_name}" alt="${img.file_name}" loading="lazy" class="w-full h-full object-cover">
            </div>
            <div class="p-3">
                <div class="flex items-center justify-between gap-2 mb-1">
                    <div class="font-medium text-sm text-gray-800 truncate flex-1">${characterText}</div>
                    <span class="confirm-badge ${img.confirmed ? 'confirmed' : 'unconfirmed'}" title="${img.confirmed ? '已确认' : '未确认'}">
                        ${img.confirmed ? '✓' : '⚠'}
                    </span>
                </div>
                <div class="text-xs text-gray-500 truncate">${tagsText || '无标签'}</div>
            </div>
        `;
        
        card.addEventListener('click', () => openDetail(img.id));
        imageGrid.appendChild(card);
    });
    
    lucide.createIcons();
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

// 加载统计信息
let statsChart = null;

async function loadStats() {
    const days = parseInt(document.getElementById('stats-days')?.value || 7);
    
    try {
        const response = await fetch(`${API_BASE}/api/stats?days=${days}`);
        const data = await response.json();
        
        if (data.success) {
            // 更新统计卡片
            document.getElementById('stats-total').textContent = data.total || 0;
            document.getElementById('stats-confirmed').textContent = data.confirmed || 0;
            document.getElementById('stats-unconfirmed').textContent = data.unconfirmed || 0;
            document.getElementById('stats-today').textContent = data.today_new || 0;
            
            // 更新图表
            updateStatsChart(data.daily || []);
        }
    } catch (e) {
        console.error('加载统计失败:', e);
    }
}

// 更新统计图表
function updateStatsChart(dailyData) {
    const ctx = document.getElementById('stats-chart');
    if (!ctx) return;
    
    const labels = dailyData.map(d => d.label);
    const counts = dailyData.map(d => d.count);
    
    if (statsChart) {
        statsChart.destroy();
    }
    
    statsChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: '新增图片数',
                data: counts,
                borderColor: '#9B59B6',
                backgroundColor: 'rgba(155, 89, 182, 0.1)',
                fill: true,
                tension: 0.4,
                pointBackgroundColor: '#9B59B6',
                pointBorderColor: '#fff',
                pointBorderWidth: 2,
                pointRadius: 4,
                pointHoverRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    backgroundColor: 'rgba(155, 89, 182, 0.9)',
                    titleColor: '#fff',
                    bodyColor: '#fff',
                    padding: 12,
                    cornerRadius: 8
                }
            },
            scales: {
                x: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        color: '#6B7280'
                    }
                },
                y: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)'
                    },
                    ticks: {
                        color: '#6B7280',
                        stepSize: 1
                    }
                }
            }
        }
    });
}
 
// 点击详情弹窗外部的处理函数
async function handleDetailOverlayClick() {
    await autoSaveAndClose();
}

// 自动保存并关闭弹窗
async function autoSaveAndClose() {
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
            showToast('保存成功', 'success');
            loadImages();
        } else {
            showToast('保存失败: ' + data.error, 'error');
        }
    } catch (e) {
        showToast('保存失败: ' + e, 'error');
    } finally {
        detailModal.classList.add('hidden');
    }
}

// 打开详情弹窗
async function openDetail(imageId) {
    currentImageId = imageId;
    
    try {
        const response = await fetch(`${API_BASE}/api/images/${imageId}`);
        const data = await response.json();
        
        if (data.success) {
            const img = data.image;
            
            document.getElementById('detail-image').src = `${API_BASE}/images/${img.file_name}`;
            document.getElementById('detail-filename').textContent = img.file_name;
            document.getElementById('detail-group').textContent = img.group_id;
            document.getElementById('detail-sender').textContent = img.sender_id;
            document.getElementById('detail-time').textContent = new Date(img.timestamp * 1000).toLocaleString();
            document.getElementById('detail-description').value = img.description || '';
            
            window._currentConfirmed = img.confirmed || 0;
            
            renderCharacterEditor(img.character);
            
            const tagsContainer = document.getElementById('detail-tags');
            tagsContainer.innerHTML = '';
            if (img.tags) {
                Object.entries(img.tags).forEach(([category, tags]) => {
                    tags.forEach(tag => {
                        const tagEl = document.createElement('span');
                        tagEl.className = 'px-2 py-1 bg-purple-100 text-purple-700 text-xs rounded-full';
                        tagEl.textContent = tag;
                        tagsContainer.appendChild(tagEl);
                    });
                });
            }
            
            detailModal.classList.remove('hidden');
            lucide.createIcons();
        }
    } catch (e) {
        console.error('加载详情失败:', e);
    }
}

// 渲染角色编辑器
function renderCharacterEditor(characterJson) {
    const container = document.querySelector('.character-list');
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
    
    characters.forEach((char, index) => {
        addCharacterRow(char.name, char.work);
    });
    
    document.getElementById('add-character-btn').onclick = () => addCharacterRow('', '');
}

// 添加一行角色输入
function addCharacterRow(name = '', work = '') {
    const container = document.querySelector('.character-list');
    const row = document.createElement('div');
    row.className = 'flex gap-2 items-center';
    row.innerHTML = `
        <input type="text" class="char-name flex-1 px-3 py-2 rounded-lg border border-gray-200 focus:border-purple-400 outline-none text-sm" placeholder="角色名" value="${name || ''}">
        <input type="text" class="work-input flex-1 px-3 py-2 rounded-lg border border-gray-200 focus:border-purple-400 outline-none text-sm" placeholder="作品名" value="${work || ''}">
        <button type="button" class="remove-char-btn p-2 bg-red-100 text-red-600 rounded-lg hover:bg-red-200 transition">
            <i data-lucide="trash-2" class="w-4 h-4"></i>
        </button>
    `;
    
    row.querySelector('.remove-char-btn').onclick = () => {
        container.removeChild(row);
    };
    
    container.appendChild(row);
    lucide.createIcons();
}

// 获取角色编辑器中的数据并转换为JSON
function getCharacterJson() {
    const characters = [];
    
    document.querySelectorAll('.character-list .flex.gap-2').forEach(row => {
        const name = row.querySelector('.char-name').value.trim();
        const work = row.querySelector('.work-input').value.trim();
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
}

function showMainPage() {
    loginPage.classList.add('hidden');
    mainPage.classList.remove('hidden');
}

// 别名管理
const aliasModal = document.getElementById('alias-modal');

let aliasCurrentPage = 1;
let aliasTotalPages = 1;
let aliasPageSize = 25;
let aliasTotal = 0;

// 加载别名列表
async function loadAliases() {
    const search = document.getElementById('search-alias').value;
    const typeFilter = document.getElementById('alias-type-filter').value;
    aliasPageSize = parseInt(document.getElementById('alias-page-size').value);
    
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
            aliasTotalPages = data.total_pages;
            renderAliases(data.aliases);
            updateAliasPagination();
        }
    } catch (e) {
        console.error('加载别名失败:', e);
    }
}

// 更新别名分页信息
function updateAliasPagination() {
    document.getElementById('alias-page-info').textContent = 
        `第 ${aliasCurrentPage} / ${aliasTotalPages} 页 (共 ${aliasTotal} 条)`;
    document.getElementById('alias-prev-page').disabled = aliasCurrentPage <= 1;
    document.getElementById('alias-next-page').disabled = aliasCurrentPage >= aliasTotalPages;
}

// 渲染别名列表
function renderAliases(aliases) {
    const aliasList = document.getElementById('alias-list');
    aliasList.innerHTML = '';
    
    if (aliases.length === 0) {
        aliasList.innerHTML = '<p class="text-center py-10 text-gray-400">暂无别名</p>';
        return;
    }
    
    aliases.forEach(alias => {
        const item = document.createElement('div');
        item.className = 'flex items-center gap-3 p-3 bg-white/50 rounded-lg hover:bg-white/70 transition';
        item.innerHTML = `
            <span class="px-2 py-1 text-xs font-medium rounded ${alias.alias_type === 'character' ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'}">
                ${alias.alias_type === 'character' ? '角色' : '作品'}
            </span>
            <span class="flex-1 font-medium">${alias.original_name}</span>
            <i data-lucide="arrow-right" class="w-4 h-4 text-gray-400"></i>
            <span class="flex-1 text-gray-600">${alias.alias}</span>
            <button class="delete-alias-btn p-2 text-red-500 hover:bg-red-50 rounded-lg transition" data-id="${alias.id}">
                <i data-lucide="trash-2" class="w-4 h-4"></i>
            </button>
        `;
        
        item.querySelector('.delete-alias-btn').addEventListener('click', async (e) => {
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
        
        aliasList.appendChild(item);
    });
    
    lucide.createIcons();
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
                    btn.innerHTML = '<i data-lucide="upload" class="w-4 h-4 inline mr-1"></i>导入';
                    lucide.createIcons();
                    
                    showToast(`导入完成: 共导入 ${data.imported} 个别名`, 'success');
                    loadAliases();
                }
            }
        } catch (e) {
            console.error('获取进度失败:', e);
        }
    }, 500);
}
