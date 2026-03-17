const API_BASE = '';

let currentPage = 0;
let pageSize = 20;
let totalImages = 0;
let currentImageId = null;
let searchParams = {
    tag: '',
    character: '',
    description: ''
};

// DOM 元素
const loginPage = document.getElementById('login-page');
const mainPage = document.getElementById('main-page');
const loginForm = document.getElementById('login-form');
const loginError = document.getElementById('login-error');
const imageGrid = document.getElementById('image-grid');
const imageCount = document.getElementById('image-count');
const detailModal = document.getElementById('detail-modal');

// 页面加载时检查登录状态
document.addEventListener('DOMContentLoaded', async () => {
    await checkAuth();
});

// 检查登录状态
async function checkAuth() {
    try {
        const response = await fetch(`${API_BASE}/api/auth/info`);
        const data = await response.json();
        if (data.success && data.logged_in) {
            showMainPage();
            await cleanupMissingFiles();
            loadImages();
        } else {
            showLoginPage();
        }
    } catch (e) {
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

// 登录表单提交
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
        } else {
            loginError.textContent = data.error || '登录失败';
        }
    } catch (e) {
        loginError.textContent = '网络错误';
    }
});

// 退出登录
document.getElementById('logout-btn').addEventListener('click', async () => {
    await fetch(`${API_BASE}/api/auth/logout`, { method: 'POST' });
    showLoginPage();
});

// 搜索
document.getElementById('search-btn').addEventListener('click', () => {
    searchParams.tag = document.getElementById('search-tag').value;
    searchParams.character = document.getElementById('search-character').value;
    searchParams.description = document.getElementById('search-description').value;
    currentPage = 0;
    loadImages();
});

// 清除搜索
document.getElementById('clear-search-btn').addEventListener('click', () => {
    document.getElementById('search-tag').value = '';
    document.getElementById('search-character').value = '';
    document.getElementById('search-description').value = '';
    searchParams = { tag: '', character: '', description: '' };
    currentPage = 0;
    loadImages();
});

// 分页
document.getElementById('prev-page').addEventListener('click', () => {
    if (currentPage > 0) {
        currentPage--;
        loadImages();
    }
});

document.getElementById('next-page').addEventListener('click', () => {
    if ((currentPage + 1) * pageSize < totalImages) {
        currentPage++;
        loadImages();
    }
});

// 加载图片列表
async function loadImages() {
    const params = new URLSearchParams();
    if (searchParams.tag) params.append('tag', searchParams.tag);
    if (searchParams.character) params.append('character', searchParams.character);
    if (searchParams.description) params.append('description', searchParams.description);
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

// 渲染图片列表
function renderImages(images) {
    imageGrid.innerHTML = '';
    
    if (images.length === 0) {
        imageGrid.innerHTML = '<p style="text-align:center;grid-column:1/-1;color:#666;">暂无图片</p>';
        return;
    }

    images.forEach(img => {
        const card = document.createElement('div');
        card.className = 'image-card';
        
        let tagsText = '';
        if (img.tags) {
            const allTags = Object.values(img.tags).flat();
            tagsText = allTags.slice(0, 3).join(', ');
        }
        
        card.innerHTML = `
            <img src="${API_BASE}/images/${img.file_name}" alt="${img.file_name}">
            <div class="image-card-info">
                <div class="character">${img.character || '未知角色'}</div>
                <div class="tags">${tagsText || img.description || '无标签'}</div>
            </div>
        `;
        
        card.addEventListener('click', () => openDetail(img.id));
        imageGrid.appendChild(card);
    });
}

// 更新分页信息
function updatePagination() {
    const totalPages = Math.ceil(totalImages / pageSize) || 1;
    document.getElementById('page-info').textContent = `第 ${currentPage + 1} / ${totalPages} 页`;
    document.getElementById('image-count').textContent = `共 ${totalImages} 张图片`;
    document.getElementById('prev-page').disabled = currentPage === 0;
    document.getElementById('next-page').disabled = (currentPage + 1) * pageSize >= totalImages;
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
            document.getElementById('detail-character').value = img.character || '';
            document.getElementById('detail-description').value = img.description || '';
            
            // 渲染标签
            const tagsContainer = document.getElementById('detail-tags');
            tagsContainer.innerHTML = '';
            if (img.tags) {
                Object.entries(img.tags).forEach(([category, tags]) => {
                    tags.forEach(tag => {
                        const tagEl = document.createElement('span');
                        tagEl.className = 'tag';
                        tagEl.textContent = tag;
                        tagsContainer.appendChild(tagEl);
                    });
                });
            }
            
            detailModal.classList.remove('hidden');
        }
    } catch (e) {
        console.error('加载详情失败:', e);
    }
}

// 关闭详情弹窗
document.querySelector('.close').addEventListener('click', () => {
    detailModal.classList.add('hidden');
});

detailModal.addEventListener('click', (e) => {
    if (e.target === detailModal) {
        detailModal.classList.add('hidden');
    }
});

// 保存详情
document.getElementById('save-detail-btn').addEventListener('click', async () => {
    const character = document.getElementById('detail-character').value;
    const description = document.getElementById('detail-description').value;
    
    try {
        const response = await fetch(`${API_BASE}/api/images/${currentImageId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ character, description })
        });
        const data = await response.json();
        
        if (data.success) {
            alert('保存成功');
            loadImages();
        } else {
            alert('保存失败: ' + data.error);
        }
    } catch (e) {
        alert('保存失败: ' + e);
    }
});

// AI 重新分析
document.getElementById('reanalyze-btn').addEventListener('click', async () => {
    if (!confirm('确定要重新分析这张图片吗？')) return;
    
    const btn = document.getElementById('reanalyze-btn');
    btn.disabled = true;
    btn.textContent = '分析中...';
    
    try {
        const response = await fetch(`${API_BASE}/api/images/${currentImageId}/reanalyze`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            alert('重新分析完成');
            openDetail(currentImageId);
            loadImages();
        } else {
            alert('重新分析失败: ' + data.error);
        }
    } catch (e) {
        alert('重新分析失败: ' + e);
    } finally {
        btn.disabled = false;
        btn.textContent = 'AI重新分析';
    }
});

// 识别角色
document.getElementById('recognize-btn').addEventListener('click', async () => {
    if (!confirm('确定要识别这张图片的角色吗？')) return;
    
    const btn = document.getElementById('recognize-btn');
    btn.disabled = true;
    btn.textContent = '识别中...';
    
    try {
        const response = await fetch(`${API_BASE}/api/images/${currentImageId}/recognize_character`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            alert(`角色识别完成\n角色: ${data.character}\nAI检测: ${data.result?.ai_detect || 'unknown'}`);
            openDetail(currentImageId);
            loadImages();
        } else {
            alert('角色识别失败: ' + data.error);
        }
    } catch (e) {
        alert('角色识别失败: ' + e);
    } finally {
        btn.disabled = false;
        btn.textContent = '识别角色';
    }
});

// 删除图片
document.getElementById('delete-btn').addEventListener('click', async () => {
    if (!confirm('确定要删除这张图片吗？此操作不可恢复！')) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/images/${currentImageId}`, {
            method: 'DELETE'
        });
        const data = await response.json();
        
        if (data.success) {
            alert('删除成功');
            detailModal.classList.add('hidden');
            loadImages();
        } else {
            alert('删除失败: ' + data.error);
        }
    } catch (e) {
        alert('删除失败: ' + e);
    }
});

// 页面切换
function showLoginPage() {
    loginPage.classList.remove('hidden');
    mainPage.classList.add('hidden');
}

function showMainPage() {
    loginPage.classList.add('hidden');
    mainPage.classList.remove('hidden');
}

// 标签切换
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const tabName = btn.dataset.tab;
        
        // 更新按钮状态
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        
        // 更新内容显示
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.add('hidden');
        });
        document.getElementById(`tab-${tabName}`).classList.remove('hidden');
        
        // 如果切换到别名管理，加载别名列表
        if (tabName === 'aliases') {
            aliasCurrentPage = 1;
            loadAliases();
        }
    });
});

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

// 更新分页信息
function updateAliasPagination() {
    document.getElementById('alias-page-info').textContent = 
        `第 ${aliasCurrentPage} / ${aliasTotalPages} 页 (共 ${aliasTotal} 条)`;
    document.getElementById('alias-prev-page').disabled = aliasCurrentPage <= 1;
    document.getElementById('alias-next-page').disabled = aliasCurrentPage >= aliasTotalPages;
}

// 别名分页事件
document.getElementById('alias-prev-page').addEventListener('click', () => {
    if (aliasCurrentPage > 1) {
        aliasCurrentPage--;
        loadAliases();
    }
});

document.getElementById('alias-next-page').addEventListener('click', () => {
    if (aliasCurrentPage < aliasTotalPages) {
        aliasCurrentPage++;
        loadAliases();
    }
});

document.getElementById('alias-page-size').addEventListener('change', () => {
    aliasCurrentPage = 1;
    loadAliases();
});

// 渲染别名列表
function renderAliases(aliases) {
    const aliasList = document.getElementById('alias-list');
    aliasList.innerHTML = '';
    
    if (aliases.length === 0) {
        aliasList.innerHTML = '<p style="text-align:center;padding:40px;color:#666;">暂无别名</p>';
        return;
    }
    
    aliases.forEach(alias => {
        const item = document.createElement('div');
        item.className = 'alias-item';
        item.innerHTML = `
            <span class="alias-type ${alias.alias_type}">${alias.alias_type === 'character' ? '角色' : '作品'}</span>
            <span class="alias-original">${alias.original_name}</span>
            <span class="arrow">→</span>
            <span class="alias-name">${alias.alias}</span>
            <button class="delete-alias-btn" data-id="${alias.id}">删除</button>
        `;
        
        item.querySelector('.delete-alias-btn').addEventListener('click', async (e) => {
            if (!confirm('确定要删除这个别名吗？')) return;
            
            const aliasId = e.target.dataset.id;
            try {
                const response = await fetch(`${API_BASE}/api/aliases/${aliasId}`, {
                    method: 'DELETE'
                });
                const data = await response.json();
                
                if (data.success) {
                    alert('删除成功');
                    loadAliases();
                } else {
                    alert('删除失败: ' + data.error);
                }
            } catch (e) {
                alert('删除失败: ' + e);
            }
        });
        
        aliasList.appendChild(item);
    });
}

// 搜索别名
document.getElementById('search-alias-btn').addEventListener('click', () => {
    aliasCurrentPage = 1;
    loadAliases();
});

// 回车搜索别名
document.getElementById('search-alias').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        aliasCurrentPage = 1;
        loadAliases();
    }
});

// 筛选类型变化时重新加载
document.getElementById('alias-type-filter').addEventListener('change', () => {
    aliasCurrentPage = 1;
    loadAliases();
});

let importPollInterval = null;

// 从文件导入别名
document.getElementById('import-alias-btn').addEventListener('click', async () => {
    if (!confirm('确定要从 aliases.json 导入别名吗？')) return;
    
    const btn = document.getElementById('import-alias-btn');
    btn.disabled = true;
    btn.textContent = '启动中...';
    
    try {
        const response = await fetch(`${API_BASE}/api/aliases/import`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            btn.textContent = '导入中...';
            document.getElementById('import-progress').classList.remove('hidden');
            startImportPoll();
        } else {
            alert('导入失败: ' + data.error);
            btn.disabled = false;
            btn.textContent = '从文件导入';
        }
    } catch (e) {
        alert('导入失败: ' + e);
        btn.disabled = false;
        btn.textContent = '从文件导入';
    }
});

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
                    btn.textContent = '从文件导入';
                    
                    alert(`导入完成: 共导入 ${data.imported} 个别名`);
                    loadAliases();
                }
            }
        } catch (e) {
            console.error('获取进度失败:', e);
        }
    }, 500);
}

// 停止导入
document.getElementById('stop-import-btn').addEventListener('click', async () => {
    if (!confirm('确定要停止导入吗？')) return;
    
    try {
        await fetch(`${API_BASE}/api/aliases/import/stop`, {
            method: 'POST'
        });
    } catch (e) {
        console.error('停止导入失败:', e);
    }
});

// 添加别名按钮
document.getElementById('add-alias-btn').addEventListener('click', () => {
    aliasModal.classList.remove('hidden');
});

// 关闭添加别名弹窗
document.querySelector('.close-alias').addEventListener('click', () => {
    aliasModal.classList.add('hidden');
});

document.getElementById('cancel-alias-btn').addEventListener('click', () => {
    aliasModal.classList.add('hidden');
});

aliasModal.addEventListener('click', (e) => {
    if (e.target === aliasModal) {
        aliasModal.classList.add('hidden');
    }
});

// 提交添加别名表单
document.getElementById('add-alias-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const aliasType = document.getElementById('alias-type').value;
    const originalName = document.getElementById('alias-original').value;
    const aliasName = document.getElementById('alias-name').value;
    
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
            alert('添加成功');
            aliasModal.classList.add('hidden');
            document.getElementById('add-alias-form').reset();
            loadAliases();
        } else {
            alert('添加失败: ' + data.error);
        }
    } catch (e) {
        alert('添加失败: ' + e);
    }
});
