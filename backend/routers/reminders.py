"""
提醒服务 - 后端定时任务
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timedelta
from typing import List, Optional

from database import get_db
from models import Ticket, FollowUp
from schemas import success_response, error_response

router = APIRouter()


@router.get("/reminders", response_model=dict)
def get_reminders(
    unread_only: bool = False,
    assignee: str = None,
    db: Session = Depends(get_db)
):
    """获取提醒列表（基于超期工单自动生成）"""
    now = datetime.now()
    reminders = []
    
    # 查询所有未关闭的工单
    query = db.query(Ticket).filter(Ticket.status.in_(["pending", "processing", "waiting_feedback"]))
    if assignee:
        query = query.filter(Ticket.assignee == assignee)
    
    tickets = query.all()
    
    for ticket in tickets:
        # 待处理超过24小时
        if ticket.status == "pending" and ticket.created_at:
            elapsed = now - ticket.created_at
            if elapsed > timedelta(hours=24):
                reminders.append({
                    "id": f"T{ticket.id}_pending",
                    "ticket_id": ticket.id,
                    "title": ticket.title,
                    "type": "overdue",
                    "level": "danger",
                    "message": f"工单【{ticket.title}】待处理已超 {elapsed.days}天{elapsed.seconds//3600}小时",
                    "assignee": ticket.assignee,
                    "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
                    "is_read": False
                })
        
        # 处理中超过48小时
        elif ticket.status == "processing" and ticket.started_at:
            elapsed = now - ticket.started_at
            if elapsed > timedelta(hours=48):
                reminders.append({
                    "id": f"T{ticket.id}_processing",
                    "ticket_id": ticket.id,
                    "title": ticket.title,
                    "type": "overdue",
                    "level": "danger",
                    "message": f"工单【{ticket.title}】处理中已超 {elapsed.days}天{elapsed.seconds//3600}小时",
                    "assignee": ticket.assignee,
                    "created_at": ticket.started_at.isoformat() if ticket.started_at else None,
                    "is_read": False
                })
        
        # 等待反馈超过72小时
        elif ticket.status == "waiting_feedback":
            # 使用最后更新时间或创建时间
            check_time = ticket.resolved_at or ticket.started_at or ticket.created_at
            if check_time:
                elapsed = now - check_time
                if elapsed > timedelta(hours=72):
                    reminders.append({
                        "id": f"T{ticket.id}_waiting",
                        "ticket_id": ticket.id,
                        "title": ticket.title,
                        "type": "follow_up",
                        "level": "warning",
                        "message": f"工单【{ticket.title}】等待客户反馈已超 {elapsed.days}天，建议催办",
                        "assignee": ticket.assignee,
                        "created_at": check_time.isoformat() if check_time else None,
                        "is_read": False
                    })
    
    # 按严重程度排序
    level_order = {"danger": 0, "warning": 1, "info": 2}
    reminders.sort(key=lambda x: (level_order.get(x["level"], 3), x["created_at"] or ""))
    
    # 统计
    unread_count = len([r for r in reminders if not r["is_read"]])
    
    return success_response({
        "items": reminders,
        "total": len(reminders),
        "unread_count": unread_count
    })


@router.get("/reminders/stats", response_model=dict)
def get_reminder_stats(assignee: str = None, db: Session = Depends(get_db)):
    """获取提醒统计（用于导航栏红点）"""
    now = datetime.now()
    count = 0
    
    query = db.query(Ticket).filter(Ticket.status.in_(["pending", "processing", "waiting_feedback"]))
    if assignee:
        query = query.filter(Ticket.assignee == assignee)
    
    tickets = query.all()
    
    for ticket in tickets:
        if ticket.status == "pending" and ticket.created_at:
            if (now - ticket.created_at) > timedelta(hours=24):
                count += 1
        elif ticket.status == "processing" and ticket.started_at:
            if (now - ticket.started_at) > timedelta(hours=48):
                count += 1
        elif ticket.status == "waiting_feedback":
            check_time = ticket.resolved_at or ticket.started_at or ticket.created_at
            if check_time and (now - check_time) > timedelta(hours=72):
                count += 1
    
    return success_response({"count": count})
