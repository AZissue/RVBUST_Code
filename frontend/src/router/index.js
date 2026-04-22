import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Customers from '../views/Customers.vue'
import CustomerDetail from '../views/CustomerDetail.vue'
import Tickets from '../views/Tickets.vue'
import TicketDetail from '../views/TicketDetail.vue'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard,
    meta: { title: '工作台' }
  },
  {
    path: '/customers',
    name: 'Customers',
    component: Customers,
    meta: { title: '客户管理' }
  },
  {
    path: '/customers/:id',
    name: 'CustomerDetail',
    component: CustomerDetail,
    meta: { title: '客户详情' }
  },
  {
    path: '/tickets',
    name: 'Tickets',
    component: Tickets,
    meta: { title: '工单管理' }
  },
  {
    path: '/tickets/:id',
    name: 'TicketDetail',
    component: TicketDetail,
    meta: { title: '工单详情' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
