"""
数据导入导出路由
支持 JSON 完整备份和 CSV 表格导出
"""
from fastapi import APIRouter, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
import json
import csv
import io
from datetime import datetime
from typing import List, Dict, Any

from database import get_db
from models import Customer, Device, Ticket, FollowUp
from schemas import success_response, error_response

router = APIRouter()


@router.get("/export/json")
def export_json(db: Session = Depends(get_db)):
    """导出所有数据为 JSON（完整备份）"""
    data = {
        "export_time": datetime.now().isoformat(),
        "version": "1.0",
        "customers": [],
        "devices": [],
        "tickets": [],
        "follow_ups": []
    }
    
    # 导出客户
    for c in db.query(Customer).all():
        data["customers"].append({
            "id": c.id,
            "name": c.name,
            "contact_person": c.contact_person,
            "phone": c.phone,
            "email": c.email,
            "region": c.region,
            "industry": c.industry,
            "activity_level": c.activity_level,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "last_contact_at": c.last_contact_at.isoformat() if c.last_contact_at else None
        })
    
    # 导出设备
    for d in db.query(Device).all():
        data["devices"].append({
            "id": d.id,
            "customer_id": d.customer_id,
            "model": d.model,
            "serial_number": d.serial_number,
            "firmware_version": d.firmware_version,
            "purchase_date": d.purchase_date.isoformat() if d.purchase_date else None,
            "created_at": d.created_at.isoformat() if d.created_at else None
        })
    
    # 导出工单
    for t in db.query(Ticket).all():
        data["tickets"].append({
            "id": t.id,
            "customer_id": t.customer_id,
            "device_id": t.device_id,
            "title": t.title,
            "category": t.category,
            "description": t.description,
            "solution": t.solution,
            "status": t.status,
            "priority": t.priority,
            "assignee": t.assignee,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
            "closed_at": t.closed_at.isoformat() if t.closed_at else None
        })
    
    # 导出跟进记录
    for f in db.query(FollowUp).all():
        data["follow_ups"].append({
            "id": f.id,
            "ticket_id": f.ticket_id,
            "content": f.content,
            "type": f.type,
            "created_by": f.created_by,
            "created_at": f.created_at.isoformat() if f.created_at else None
        })
    
    # 生成文件流
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    buffer = io.BytesIO(json_str.encode('utf-8'))
    
    filename = f"tech_support_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    return StreamingResponse(
        buffer,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/export/csv")
def export_csv(db: Session = Depends(get_db)):
    """导出工单为 CSV（表格格式，方便Excel查看）"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    # 表头
    writer.writerow([
        "工单编号", "客户名称", "问题类型", "标题", "状态", "优先级",
        "负责人", "创建时间", "开始处理时间", "解决时间", "详细描述", "解决方案"
    ])
    
    # 数据
    tickets = db.query(Ticket).all()
    for t in tickets:
        customer_name = t.customer.name if t.customer else ""
        writer.writerow([
            t.id,
            customer_name,
            t.category or "",
            t.title,
            t.status,
            t.priority,
            t.assignee or "",
            t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "",
            t.started_at.strftime("%Y-%m-%d %H:%M") if t.started_at else "",
            t.resolved_at.strftime("%Y-%m-%d %H:%M") if t.resolved_at else "",
            t.description or "",
            t.solution or ""
        ])
    
    # 生成文件流
    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))  # utf-8-sig 让Excel正确识别中文
    output.close()
    
    filename = f"tech_support_tickets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return StreamingResponse(
        buffer,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post("/import/json")
def import_json(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """从 JSON 文件导入数据（恢复备份）"""
    try:
        content = file.file.read().decode('utf-8')
        data = json.loads(content)
        
        # 验证格式
        if not all(k in data for k in ["customers", "tickets"]):
            return error_response("文件格式不正确，缺少必要字段", 400)
        
        imported = {"customers": 0, "devices": 0, "tickets": 0, "follow_ups": 0}
        
        # 导入客户
        if data.get("customers"):
            for c in data["customers"]:
                # 检查是否已存在
                existing = db.query(Customer).filter(Customer.name == c.get("name")).first()
                if existing:
                    continue
                
                customer = Customer(
                    name=c.get("name"),
                    contact_person=c.get("contact_person"),
                    phone=c.get("phone"),
                    email=c.get("email"),
                    region=c.get("region"),
                    industry=c.get("industry"),
                    activity_level=c.get("activity_level", "medium")
                )
                db.add(customer)
                imported["customers"] += 1
            db.commit()
        
        # 导入设备
        if data.get("devices"):
            for d in data["devices"]:
                device = Device(
                    customer_id=d.get("customer_id"),
                    model=d.get("model"),
                    serial_number=d.get("serial_number"),
                    firmware_version=d.get("firmware_version")
                )
                db.add(device)
                imported["devices"] += 1
            db.commit()
        
        # 导入工单
        if data.get("tickets"):
            for t in data["tickets"]:
                ticket = Ticket(
                    customer_id=t.get("customer_id"),
                    device_id=t.get("device_id"),
                    title=t.get("title"),
                    category=t.get("category"),
                    description=t.get("description"),
                    solution=t.get("solution"),
                    status=t.get("status", "pending"),
                    priority=t.get("priority", "normal"),
                    assignee=t.get("assignee")
                )
                db.add(ticket)
                imported["tickets"] += 1
            db.commit()
        
        # 导入跟进记录
        if data.get("follow_ups"):
            for f in data["follow_ups"]:
                follow = FollowUp(
                    ticket_id=f.get("ticket_id"),
                    content=f.get("content"),
                    type=f.get("type", "comment"),
                    created_by=f.get("created_by", "系统")
                )
                db.add(follow)
                imported["follow_ups"] += 1
            db.commit()
        
        return success_response(imported, f"导入成功：客户{imported['customers']}个，工单{imported['tickets']}个，跟进记录{imported['follow_ups']}条")
    
    except json.JSONDecodeError:
        return error_response("文件格式错误，请上传有效的JSON文件", 400)
    except Exception as e:
        return error_response(f"导入失败：{str(e)}", 500)


@router.get("/export/customers/csv")
def export_customers_csv(db: Session = Depends(get_db)):
    """导出客户列表为 CSV"""
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(["客户名称", "联系人", "电话", "邮箱", "地区", "行业", "活跃度"])
    
    customers = db.query(Customer).all()
    for c in customers:
        writer.writerow([
            c.name,
            c.contact_person or "",
            c.phone or "",
            c.email or "",
            c.region or "",
            c.industry or "",
            c.activity_level or "medium"
        ])
    
    buffer = io.BytesIO(output.getvalue().encode('utf-8-sig'))
    output.close()
    
    filename = f"tech_support_customers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return StreamingResponse(
        buffer,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
