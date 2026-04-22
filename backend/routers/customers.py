"""
客户管理路由
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from typing import List, Optional

from database import get_db
from models import Customer, Device, Ticket, FollowUp
from schemas import (
    success_response, error_response,
    CustomerCreate, CustomerUpdate, CustomerResponse,
    CustomerSearchResult, CustomerDetailResponse, TimelineItem
)

router = APIRouter()


@router.get("", response_model=dict)
def get_customers(
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """客户列表（支持搜索分页）"""
    query = db.query(Customer)
    
    if q:
        search = f"%{q}%"
        query = query.filter(
            or_(
                Customer.name.ilike(search),
                Customer.contact_person.ilike(search),
                Customer.phone.ilike(search),
                Customer.region.ilike(search)
            )
        )
    
    total = query.count()
    customers = query.order_by(Customer.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    
    return success_response({
        "items": [CustomerResponse.model_validate(c).model_dump() for c in customers],
        "total": total,
        "page": page,
        "page_size": page_size
    })


@router.get("/search", response_model=dict)
def search_customers(q: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    """客户搜索（自动补全用）"""
    search = f"%{q}%"
    customers = db.query(Customer).filter(
        or_(
            Customer.name.ilike(search),
            Customer.contact_person.ilike(search)
        )
    ).limit(10).all()
    
    results = [CustomerSearchResult(
        id=c.id,
        name=c.name,
        contact_person=c.contact_person,
        region=c.region
    ) for c in customers]
    
    return success_response([r.model_dump() for r in results])


@router.get("/{customer_id}", response_model=dict)
def get_customer_detail(customer_id: int, db: Session = Depends(get_db)):
    """客户详情（含设备清单和时间轴）"""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return error_response("客户不存在", 404)
    
    # 手动构建响应，避免model_validate问题
    result = {
        "id": customer.id,
        "name": customer.name,
        "contact_person": customer.contact_person,
        "phone": customer.phone,
        "email": customer.email,
        "region": customer.region,
        "industry": customer.industry,
        "activity_level": customer.activity_level,
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
        "last_contact_at": customer.last_contact_at.isoformat() if customer.last_contact_at else None,
        "devices": [],
        "timeline": []
    }
    
    # 设备清单
    for d in customer.devices:
        result["devices"].append({
            "id": d.id,
            "customer_id": d.customer_id,
            "model": d.model,
            "serial_number": d.serial_number,
            "firmware_version": d.firmware_version,
            "purchase_date": d.purchase_date.isoformat() if d.purchase_date else None,
            "created_at": d.created_at.isoformat() if d.created_at else None
        })
    
    # 构建时间轴：工单 + 跟进记录
    timeline = []
    
    for ticket in customer.tickets:
        timeline.append({
            "id": ticket.id,
            "type": "ticket",
            "title": ticket.title,
            "content": ticket.description,
            "status": ticket.status,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None
        })
        for follow in ticket.follow_ups:
            timeline.append({
                "id": follow.id,
                "type": "follow_up",
                "content": follow.content,
                "status": follow.type,
                "created_at": follow.created_at.isoformat() if follow.created_at else None
            })
    
    # 按时间倒序
    timeline.sort(key=lambda x: x["created_at"] or "", reverse=True)
    result["timeline"] = timeline
    
    return success_response(result)


@router.post("", response_model=dict)
def create_customer(customer: CustomerCreate, db: Session = Depends(get_db)):
    """创建客户"""
    # 检查名称是否已存在
    existing = db.query(Customer).filter(Customer.name == customer.name).first()
    if existing:
        return error_response("客户名称已存在", 400)
    
    db_customer = Customer(**customer.model_dump())
    db.add(db_customer)
    db.commit()
    db.refresh(db_customer)
    
    return success_response(CustomerResponse.model_validate(db_customer).model_dump(), "创建成功")


@router.put("/{customer_id}", response_model=dict)
def update_customer(customer_id: int, customer: CustomerUpdate, db: Session = Depends(get_db)):
    """更新客户"""
    db_customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not db_customer:
        return error_response("客户不存在", 404)
    
    update_data = customer.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_customer, field, value)
    
    db.commit()
    db.refresh(db_customer)
    
    return success_response(CustomerResponse.model_validate(db_customer).model_dump(), "更新成功")


@router.delete("/{customer_id}", response_model=dict)
def delete_customer(customer_id: int, db: Session = Depends(get_db)):
    """删除客户"""
    db_customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not db_customer:
        return error_response("客户不存在", 404)
    
    db.delete(db_customer)
    db.commit()
    
    return success_response(message="删除成功")
