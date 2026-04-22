"""
首页工作台路由
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timedelta

from database import get_db
from models import Ticket, Customer
from schemas import success_response, error_response, DashboardStats, TodoItem

router = APIRouter()


@router.get("/stats", response_model=dict)
def get_dashboard_stats(db: Session = Depends(get_db)):
    """获取首页统计数据"""
    pending = db.query(func.count(Ticket.id)).filter(Ticket.status == "pending").scalar()
    processing = db.query(func.count(Ticket.id)).filter(Ticket.status == "processing").scalar()
    waiting = db.query(func.count(Ticket.id)).filter(Ticket.status == "waiting_feedback").scalar()
    
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    resolved_today = db.query(func.count(Ticket.id)).filter(
        Ticket.status == "resolved",
        Ticket.resolved_at >= today_start
    ).scalar()
    
    stats = DashboardStats(
        pending_count=pending or 0,
        processing_count=processing or 0,
        waiting_feedback_count=waiting or 0,
        resolved_today_count=resolved_today or 0
    )
    
    return success_response(stats.model_dump())


@router.get("/todos", response_model=dict)
def get_todo_list(assignee: str = None, db: Session = Depends(get_db)):
    """获取待办列表（按紧急程度排序）"""
    query = db.query(Ticket, Customer).join(Customer, Ticket.customer_id == Customer.id).filter(
        Ticket.status.in_(["pending", "processing", "waiting_feedback"])
    )
    
    if assignee:
        query = query.filter(Ticket.assignee == assignee)
    
    # 优先级排序：urgent > high > normal > low（SQLite兼容方式）
    results = query.order_by(Ticket.created_at.asc()).all()
    
    # Python层面按优先级排序
    priority_order = {"urgent": 1, "high": 2, "normal": 3, "low": 4}
    results.sort(key=lambda x: (priority_order.get(x[0].priority, 5), x[0].created_at or datetime.min))
    
    now = datetime.now()
    todos = []
    for ticket, customer in results:
        # 判断是否超时
        is_overdue = False
        if ticket.status == "pending" and ticket.created_at:
            is_overdue = (now - ticket.created_at) > timedelta(hours=24)
        elif ticket.status == "processing" and ticket.started_at:
            is_overdue = (now - ticket.started_at) > timedelta(hours=48)
        elif ticket.status == "waiting_feedback" and ticket.created_at:
            is_overdue = (now - ticket.created_at) > timedelta(hours=72)
        
        todos.append(TodoItem(
            id=ticket.id,
            title=ticket.title,
            customer_name=customer.name,
            status=ticket.status,
            priority=ticket.priority,
            created_at=ticket.created_at,
            is_overdue=is_overdue
        ))
    
    return success_response([todo.model_dump() for todo in todos])
