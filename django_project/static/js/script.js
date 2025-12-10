/**
 * EDS Admin Dashboard - Custom JavaScript
 * Handles sidebar interactions, active states, and UI enhancements
 */

document.addEventListener('DOMContentLoaded', function() {
    initializeSidebar();
    initializeActiveStates();
    initializeTooltips();
});

/**
 * Initialize sidebar functionality
 */
function initializeSidebar() {
    const sidebarLinks = document.querySelectorAll('.sidebar-nav .nav-link');
    
    sidebarLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            // Handle collapsed menus
            if (this.getAttribute('data-bs-toggle') === 'collapse') {
                const icon = this.querySelector('.bi-chevron-down');
                if (icon) {
                    // Bootstrap handles the collapse, we just update icon
                    const target = this.getAttribute('href');
                    const collapseElement = document.querySelector(target);
                    if (collapseElement) {
                        // Update active state when expanded
                        const isExpanding = !collapseElement.classList.contains('show');
                        if (isExpanding) {
                            sidebarLinks.forEach(l => {
                                if (l !== this && l.getAttribute('data-bs-toggle') === 'collapse') {
                                    l.classList.remove('active');
                                }
                            });
                        }
                    }
                }
            }
        });
    });
}

/**
 * Set active state based on current URL
 */
function initializeActiveStates() {
    const currentPath = window.location.pathname;
    const sidebarLinks = document.querySelectorAll('.sidebar-nav .nav-link');
    
    sidebarLinks.forEach(link => {
        const href = link.getAttribute('href');
        
        // Check if current path matches link href
        if (href && currentPath.includes(href.replace('/admin/', '').split('/')[0])) {
            link.classList.add('active');
            
            // Expand parent collapse if link is nested
            const parentCollapse = link.closest('.collapse');
            if (parentCollapse) {
                parentCollapse.classList.add('show');
                const toggleBtn = document.querySelector(`[href="#${parentCollapse.id}"]`);
                if (toggleBtn) {
                    toggleBtn.classList.remove('collapsed');
                    toggleBtn.setAttribute('aria-expanded', 'true');
                }
            }
        } else {
            link.classList.remove('active');
        }
    });
}

/**
 * Initialize Bootstrap tooltips
 */
function initializeTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

/**
 * Toggle sidebar on mobile
 */
function toggleSidebar() {
    const sidebar = document.querySelector('.sidebar');
    if (window.innerWidth <= 768) {
        sidebar.classList.toggle('collapsed');
    }
}

/**
 * Close sidebar when clicking on a link (mobile)
 */
document.addEventListener('click', function(e) {
    const sidebar = document.querySelector('.sidebar');
    const navToggle = document.querySelector('.navbar-toggler');
    
    if (window.innerWidth <= 768) {
        if (e.target.classList.contains('nav-link') && !e.target.getAttribute('data-bs-toggle')) {
            sidebar.classList.add('collapsed');
        }
    }
});

/**
 * Handle window resize
 */
window.addEventListener('resize', function() {
    const sidebar = document.querySelector('.sidebar');
    if (window.innerWidth > 768) {
        sidebar.classList.remove('collapsed');
    }
});

/**
 * Smooth scroll for anchor links
 */
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        const href = this.getAttribute('href');
        if (href !== '#' && document.querySelector(href)) {
            e.preventDefault();
            const target = document.querySelector(href);
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

/**
 * Auto-hide alerts after 5 seconds
 */
document.addEventListener('DOMContentLoaded', function() {
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });
});

/**
 * Utility: Set element as active
 */
function setActive(selector) {
    document.querySelectorAll('.nav-link.active').forEach(el => {
        el.classList.remove('active');
    });
    const element = document.querySelector(selector);
    if (element) {
        element.classList.add('active');
    }
}

/**
 * Utility: Expand collapse
 */
function expandCollapse(selector) {
    const element = document.querySelector(selector);
    if (element) {
        const collapse = new bootstrap.Collapse(element, {
            toggle: true
        });
    }
}

/**
 * Console feedback
 */
console.log('EDS Admin Dashboard initialized ✓');
