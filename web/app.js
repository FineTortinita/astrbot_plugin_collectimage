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
            loadImages();
        } else {
            showLoginPage();
        }
    } catch (e) {
        showLoginPage();
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
            const result = data.result;
            alert(`角色识别完成\n角色: ${result.character}\nAI检测: ${result.ai_detect}`);
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
