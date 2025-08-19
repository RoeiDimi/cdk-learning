// Configuration for the chat application
// Update these URLs after deployment with the actual CDK outputs
window.CHAT_CONFIG = {
    // API Gateway URLs - ALWAYS use these for API calls, NEVER use CloudFront
    API_BASE_URL: 'https://lzypp0ol5j.execute-api.us-east-1.amazonaws.com',
    
    // Individual endpoints (for reference)
    ENDPOINTS: {
        REGISTER: '/register',
        LOGIN: '/login', 
        ADD_MESSAGES: '/addMessages',
        GET_STORED_MESSAGES: '/getStoredMessages'
    },
    
    // Note: CloudFront is ONLY for static assets (HTML/JS/CSS)
    // All API calls must go directly to API Gateway to avoid HTTP 403 errors
};
