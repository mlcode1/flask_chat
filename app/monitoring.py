"""
Performance monitoring module
Tracks API response times, request counts, and system metrics
"""
import time
import threading
from functools import wraps
from flask import request, g
from collections import defaultdict
from datetime import datetime, timedelta


class PerformanceMonitor:
    """Performance monitoring system"""
    
    def __init__(self):
        self.metrics = {
            'requests': defaultdict(lambda: {'count': 0, 'total_time': 0, 'errors': 0}),
            'slow_requests': [],  # List of slow requests (>1s)
            'errors': [],  # List of error details
            'system': {
                'start_time': datetime.now(),
                'total_requests': 0,
                'total_errors': 0
            }
        }
        self.lock = threading.Lock()
        self.max_records = 1000  # Keep last 1000 slow requests/errors
    
    def track_request(self, endpoint, method, duration, status_code, error=None):
        """Track a single request"""
        with self.lock:
            key = f"{method} {endpoint}"
            
            # Update request metrics
            self.metrics['requests'][key]['count'] += 1
            self.metrics['requests'][key]['total_time'] += duration
            
            if status_code >= 400:
                self.metrics['requests'][key]['errors'] += 1
                self.metrics['system']['total_errors'] += 1
                
                # Record error details
                self.metrics['errors'].append({
                    'timestamp': datetime.now().isoformat(),
                    'endpoint': endpoint,
                    'method': method,
                    'status_code': status_code,
                    'error': str(error) if error else None
                })
                
                # Keep only last max_records errors
                if len(self.metrics['errors']) > self.max_records:
                    self.metrics['errors'] = self.metrics['errors'][-self.max_records:]
            
            # Track slow requests (>1s)
            if duration > 1.0:
                self.metrics['slow_requests'].append({
                    'timestamp': datetime.now().isoformat(),
                    'endpoint': endpoint,
                    'method': method,
                    'duration': round(duration, 3),
                    'status_code': status_code
                })
                
                # Keep only last max_records slow requests
                if len(self.metrics['slow_requests']) > self.max_records:
                    self.metrics['slow_requests'] = self.metrics['slow_requests'][-self.max_records:]
            
            self.metrics['system']['total_requests'] += 1
    
    def get_metrics(self):
        """Get all performance metrics"""
        with self.lock:
            # Calculate averages
            request_stats = {}
            for endpoint, data in self.metrics['requests'].items():
                avg_time = data['total_time'] / data['count'] if data['count'] > 0 else 0
                error_rate = (data['errors'] / data['count'] * 100) if data['count'] > 0 else 0
                
                request_stats[endpoint] = {
                    'count': data['count'],
                    'avg_time': round(avg_time, 3),
                    'errors': data['errors'],
                    'error_rate': round(error_rate, 2)
                }
            
            # Calculate uptime
            uptime = datetime.now() - self.metrics['system']['start_time']
            
            return {
                'system': {
                    'uptime': str(uptime).split('.')[0],  # Remove microseconds
                    'start_time': self.metrics['system']['start_time'].isoformat(),
                    'total_requests': self.metrics['system']['total_requests'],
                    'total_errors': self.metrics['system']['total_errors'],
                    'error_rate': round(
                        (self.metrics['system']['total_errors'] / 
                         self.metrics['system']['total_requests'] * 100) 
                        if self.metrics['system']['total_requests'] > 0 else 0, 
                        2
                    )
                },
                'endpoints': request_stats,
                'slow_requests': self.metrics['slow_requests'][-20:],  # Last 20 slow requests
                'recent_errors': self.metrics['errors'][-20:]  # Last 20 errors
            }
    
    def get_top_endpoints(self, limit=10):
        """Get top endpoints by request count"""
        with self.lock:
            sorted_endpoints = sorted(
                self.metrics['requests'].items(),
                key=lambda x: x[1]['count'],
                reverse=True
            )[:limit]
            
            return [
                {
                    'endpoint': endpoint,
                    'count': data['count'],
                    'avg_time': round(data['total_time'] / data['count'], 3) if data['count'] > 0 else 0
                }
                for endpoint, data in sorted_endpoints
            ]
    
    def get_slowest_endpoints(self, limit=10):
        """Get slowest endpoints by average response time"""
        with self.lock:
            # Filter endpoints with at least 5 requests
            valid_endpoints = [
                (endpoint, data)
                for endpoint, data in self.metrics['requests'].items()
                if data['count'] >= 5
            ]
            
            sorted_endpoints = sorted(
                valid_endpoints,
                key=lambda x: x[1]['total_time'] / x[1]['count'],
                reverse=True
            )[:limit]
            
            return [
                {
                    'endpoint': endpoint,
                    'avg_time': round(data['total_time'] / data['count'], 3),
                    'count': data['count']
                }
                for endpoint, data in sorted_endpoints
            ]
    
    def reset(self):
        """Reset all metrics"""
        with self.lock:
            self.metrics = {
                'requests': defaultdict(lambda: {'count': 0, 'total_time': 0, 'errors': 0}),
                'slow_requests': [],
                'errors': [],
                'system': {
                    'start_time': datetime.now(),
                    'total_requests': 0,
                    'total_errors': 0
                }
            }


# Global monitor instance
monitor = PerformanceMonitor()


def track_performance(f):
    """Decorator to track endpoint performance"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        error = None
        status_code = 200
        
        try:
            response = f(*args, **kwargs)
            
            # Handle different response types
            if hasattr(response, 'status_code'):
                status_code = response.status_code
            elif isinstance(response, tuple):
                status_code = response[1] if len(response) > 1 else 200
            
            return response
        except Exception as e:
            error = e
            status_code = 500
            raise
        finally:
            duration = time.time() - start_time
            endpoint = request.endpoint or request.path
            method = request.method
            
            monitor.track_request(endpoint, method, duration, status_code, error)
    
    return decorated_function


def init_app(app):
    """Initialize performance monitoring for Flask app"""
    
    @app.before_request
    def before_request():
        g.start_time = time.time()
    
    @app.after_request
    def after_request(response):
        if hasattr(g, 'start_time'):
            duration = time.time() - g.start_time
            endpoint = request.endpoint or request.path
            method = request.method
            
            monitor.track_request(endpoint, method, duration, response.status_code)
        
        return response
    
    # Add monitoring endpoints
    @app.route('/api/metrics')
    def get_metrics():
        """Get all performance metrics"""
        return monitor.get_metrics()
    
    @app.route('/api/metrics/top')
    def get_top_endpoints():
        """Get top endpoints by request count"""
        limit = request.args.get('limit', 10, type=int)
        return monitor.get_top_endpoints(limit)
    
    @app.route('/api/metrics/slowest')
    def get_slowest_endpoints():
        """Get slowest endpoints"""
        limit = request.args.get('limit', 10, type=int)
        return monitor.get_slowest_endpoints(limit)
    
    @app.route('/api/metrics/reset', methods=['POST'])
    def reset_metrics():
        """Reset all metrics"""
        monitor.reset()
        return {'status': 'reset'}
