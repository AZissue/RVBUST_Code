"""
跟进记录路由
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime

from database import get_db
from models import FollowUp, Ticket
from schemas import success_response, error_response, FollowUpCreate, FollowUpResponse

router = APIRouter()


@router.post("", response_model=dict)
def create_follow_up(data: FollowUpCreate, db: Session = Depends(get_db)):
    """添加跟进记录"""
    # 检查工单是否存在
    ticket = db.query(Ticket).filter(Ticket.id == data.ticket_id).first()
    if not ticket:
        return error_response("工单不存在", 404)
    
    follow = FollowUp(**data.model_dump())
    db.add(follow)
    db.commit()
    db.refresh(follow)
    
    # 更新客户最后联系时间
    if ticket.customer:
        ticket.customer.last_contact_at = datetime.now()
        db.commit()
    
    return success_response(FollowUpResponse.model_validate(follow).model_dump(), "添加成功")
