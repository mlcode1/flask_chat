"""
Unified error handling for the API
Provides custom exception classes and global error handlers
"""
from flask import jsonify
import logging

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Base class for API errors"""
    status_code = 500
    error_code = "internal_error"
    message = "An internal error occurred"

    def __init__(self, message=None, status_code=None, error_code=None, payload=None):
        super().__init__()
        if message is not None:
            self.message = message
        if status_code is not None:
            self.status_code = status_code
        if error_code is not None:
            self.error_code = error_code
        self.payload = payload

    def to_dict(self):
        """Convert error to dictionary format for JSON response"""
        rv = {
            "error": {
                "code": self.error_code,
                "message": self.message
            }
        }
        if self.payload:
            rv["error"]["details"] = self.payload
        return rv


# Common error subclasses
class NotFoundError(APIError):
    """Resource not found (404)"""
    status_code = 404
    error_code = "not_found"
    message = "Resource not found"


class BadRequestError(APIError):
    """Bad request (400)"""
    status_code = 400
    error_code = "bad_request"
    message = "Bad request"


class UnauthorizedError(APIError):
    """Unauthorized access (401)"""
    status_code = 401
    error_code = "unauthorized"
    message = "Unauthorized access"


class ForbiddenError(APIError):
    """Forbidden access (403)"""
    status_code = 403
    error_code = "forbidden"
    message = "Access forbidden"


class ConflictError(APIError):
    """Resource conflict (409)"""
    status_code = 409
    error_code = "conflict"
    message = "Resource conflict"


class ServiceUnavailableError(APIError):
    """Service unavailable (503)"""
    status_code = 503
    error_code = "service_unavailable"
    message = "Service temporarily unavailable"


def register_error_handlers(app):
    """Register global error handlers for the Flask app"""
    
    @app.errorhandler(APIError)
    def handle_api_error(error):
        """Handle custom API errors"""
        response = jsonify(error.to_dict())
        response.status_code = error.status_code
        return response

    @app.errorhandler(404)
    def handle_404(error):
        """Handle 404 Not Found"""
        return jsonify({
            "error": {
                "code": "not_found",
                "message": "The requested resource was not found"
            }
        }), 404

    @app.errorhandler(405)
    def handle_405(error):
        """Handle 405 Method Not Allowed"""
        return jsonify({
            "error": {
                "code": "method_not_allowed",
                "message": "The HTTP method is not allowed for this endpoint"
            }
        }), 405

    @app.errorhandler(500)
    def handle_500(error):
        """Handle 500 Internal Server Error"""
        logger.error(f"Internal server error: {error}")
        return jsonify({
            "error": {
                "code": "internal_error",
                "message": "An internal server error occurred"
            }
        }), 500

    @app.errorhandler(503)
    def handle_503(error):
        """Handle 503 Service Unavailable"""
        return jsonify({
            "error": {
                "code": "service_unavailable",
                "message": "Service temporarily unavailable"
            }
        }), 503
