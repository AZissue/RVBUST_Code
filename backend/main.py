"""
FastAPI 入口文件
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import os

from database import init_db
from routers import dashboard, customers, tickets, follow_ups, reminders, data_io
from schemas import success_response, error_response

app = FastAPI(
    title="技术支持工作记录管理系统",
    description="Tech Support CRM - 3D相机技术支持团队内部工具",
    version="1.0.0"
)

# CORS 配置（开发阶段允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["首页工作台"])
app.include_router(customers.router, prefix="/api/customers", tags=["客户管理"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["工单管理"])
app.include_router(follow_ups.router, prefix="/api/follow_ups", tags=["跟进记录"])
app.include_router(reminders.router, prefix="/api", tags=["提醒通知"])
app.include_router(data_io.router, prefix="/api/data", tags=["数据导入导出"])


@app.get("/api/health")
def health_check():
    """健康检查接口"""
    return success_response({"status": "ok", "time": datetime.now().isoformat()})

@app.on_event("startup")
async def startup_event():
    """应用启动时初始化数据库和定时任务"""
    init_db()
    # 插入示例数据（仅在空数据库时）
    from database import SessionLocal
    from models import Customer, Ticket, Device, FollowUp
    from sqlalchemy import func
    
    db = SessionLocal()
    try:
        # 检查是否已有数据
        customer_count = db.query(func.count(Customer.id)).scalar()
        if customer_count == 0:
            print("正在初始化示例数据...")
            _init_sample_data(db)
            print("示例数据初始化完成")
    finally:
        db.close()
    
    # 启动定时任务（每天 9:00 和 17:00 检查超时工单）
    scheduler = BackgroundScheduler(timezone='Asia/Shanghai')
    scheduler.add_job(
        _check_overdue_tickets,
        CronTrigger(hour='9,17', minute='0'),
        id='overdue_check',
        name='检查超时工单',
        replace_existing=True
    )
    scheduler.start()
    print("定时任务已启动：每天 9:00 和 17:00 检查超时工单")


def _check_overdue_tickets():
    """定时任务：检查超期工单并自动添加系统跟进记录"""
    from database import SessionLocal
    from models import Ticket, FollowUp
    from datetime import datetime, timedelta
    
    db = SessionLocal()
    try:
        now = datetime.now()
        tickets = db.query(Ticket).filter(
            Ticket.status.in_(["pending", "processing", "waiting_feedback"])
        ).all()
        
        for ticket in tickets:
            # 待处理超过24小时
            if ticket.status == "pending" and ticket.created_at:
                if (now - ticket.created_at) > timedelta(hours=24):
                    follow = FollowUp(
                        ticket_id=ticket.id,
                        content=f"【系统提醒】工单待处理已超24小时，请及时处理",
                        type="system",
                        created_by="系统"
                    )
                    db.add(follow)
            
            # 处理中超过48小时
            elif ticket.status == "processing" and ticket.started_at:
                if (now - ticket.started_at) > timedelta(hours=48):
                    follow = FollowUp(
                        ticket_id=ticket.id,
                        content=f"【系统提醒】工单处理中已超48小时，请关注进度",
                        type="system",
                        created_by="系统"
                    )
                    db.add(follow)
            
            # 等待反馈超过72小时
            elif ticket.status == "waiting_feedback":
                check_time = ticket.resolved_at or ticket.started_at or ticket.created_at
                if check_time and (now - check_time) > timedelta(hours=72):
                    follow = FollowUp(
                        ticket_id=ticket.id,
                        content=f"【系统提醒】等待客户反馈已超72小时，建议催办",
                        type="system",
                        created_by="系统"
                    )
                    db.add(follow)
        
        db.commit()
        print(f"[{now.strftime('%Y-%m-%d %H:%M')}] 超时工单检查完成")
    except Exception as e:
        print(f"超时工单检查失败: {e}")
    finally:
        db.close()


def _init_sample_data(db):
    """插入示例数据"""
    from models import Customer, Ticket, Device, FollowUp
    from datetime import datetime, timedelta
    
    # 预设技术员
    assignees = ["张三", "李四", "王五", "赵六", "钱七"]
    
    # 示例客户1
    c1 = Customer(
        name="某某科技有限公司",
        contact_person="王经理",
        phone="13800138001",
        email="wang@example.com",
        region="北京",
        industry="制造业",
        activity_level="high",
        last_contact_at=datetime.now() - timedelta(hours=2)
    )
    db.add(c1)
    db.flush()
    
    d1 = Device(customer_id=c1.id, model="RVC-X2", serial_number="RV2024001", firmware_version="2.1.0")
    db.add(d1)
    
    t1 = Ticket(
        customer_id=c1.id,
        device_id=d1.id,
        title="相机无法连接，指示灯不亮",
        category="硬件故障",
        description="客户反馈相机插上电源后指示灯不亮，无法被软件识别。已尝试更换USB线，问题依旧。",
        status="processing",
        priority="urgent",
        assignee="张三",
        created_at=datetime.now() - timedelta(days=1),
        started_at=datetime.now() - timedelta(hours=20)
    )
    db.add(t1)
    db.flush()
    
    f1 = FollowUp(ticket_id=t1.id, content="已联系客户，建议检查电源适配器输出电压", type="comment", created_by="张三")
    db.add(f1)
    f2 = FollowUp(ticket_id=t1.id, content="状态变更：待处理 → 处理中", type="system", created_by="系统")
    db.add(f2)
    
    # 示例客户2
    c2 = Customer(
        name="创新视觉工作室",
        contact_person="李工",
        phone="13900139002",
        region="上海",
        industry="文化创意",
        activity_level="medium",
        last_contact_at=datetime.now() - timedelta(days=2)
    )
    db.add(c2)
    db.flush()
    
    t2 = Ticket(
        customer_id=c2.id,
        title="点云拼接精度咨询",
        category="咨询",
        description="客户想了解如何提高多视角点云拼接的精度，当前误差约在2mm左右。",
        status="waiting_feedback",
        priority="normal",
        assignee="李四",
        created_at=datetime.now() - timedelta(days=3),
        started_at=datetime.now() - timedelta(days=2, hours=8)
    )
    db.add(t2)
    db.flush()
    
    f3 = FollowUp(ticket_id=t2.id, content="已发送技术文档《拼接精度优化指南》", type="comment", created_by="李四")
    db.add(f3)
    
    # 示例客户3
    c3 = Customer(
        name="精密测量研究院",
        contact_person="张教授",
        phone="13700137003",
        email="zhang@inst.edu",
        region="深圳",
        industry="科研教育",
        activity_level="high",
        last_contact_at=datetime.now() - timedelta(hours=5)
    )
    db.add(c3)
    db.flush()
    
    t3 = Ticket(
        customer_id=c3.id,
        title="SDK 升级后 API 兼容性问题",
        category="软件使用",
        description="从 SDK v2.0 升级到 v2.1 后，部分 API 调用返回参数错误。",
        status="resolved",
        priority="high",
        assignee="王五",
        created_at=datetime.now() - timedelta(days=5),
        started_at=datetime.now() - timedelta(days=4, hours=10),
        resolved_at=datetime.now() - timedelta(days=1)
    )
    db.add(t3)
    db.flush()
    
    f4 = FollowUp(ticket_id=t3.id, content="已提供迁移文档，客户确认问题解决", type="comment", created_by="王五")
    db.add(f4)
    
    t4 = Ticket(
        customer_id=c3.id,
        title="批量标定流程优化建议",
        category="咨询",
        description="希望了解如何批量处理标定数据，提高生产效率。",
        status="pending",
        priority="low",
        assignee="赵六",
        created_at=datetime.now() - timedelta(hours=8)
    )
    db.add(t4)
    
    db.commit()


# 挂载前端静态文件（生产环境）
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    print(f"挂载前端静态文件: {frontend_dist}")
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")
    print("单端口部署模式已启用：访问 http://IP:端口/ 即可使用")
else:
    print("前端静态文件目录不存在，请以开发模式运行前端")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
