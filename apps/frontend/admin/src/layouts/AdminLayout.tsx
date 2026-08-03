import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, theme } from 'antd'
import {
  DashboardOutlined,
  ApartmentOutlined,
  SettingOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  BarChartOutlined,
  SafetyOutlined,
  TeamOutlined,
  BookOutlined,
} from '@ant-design/icons'

const { Header, Sider, Content } = Layout

const menuItems = [
  {
    key: '/dashboard',
    icon: <DashboardOutlined />,
    label: '仪表盘',
  },
  {
    key: '/knowledge',
    icon: <ApartmentOutlined />,
    label: '知识图谱管理',
    children: [
      { key: '/knowledge/files', label: '资料上传' },
      { key: '/knowledge/extraction', label: '知识抽取' },
      { key: '/knowledge/chapters', label: '章节目录' },
      { key: '/knowledge/points', label: '知识点管理' },
      { key: '/knowledge/relations', label: '关系管理' },
    ],
  },
  {
    key: '/questions',
    icon: <DatabaseOutlined />,
    label: '题库与试卷管理',
    children: [
      { key: '/questions/papers', label: '试卷管理' },
      { key: '/questions/real', label: '真题题库' },
      { key: '/questions/mock', label: '模拟题库' },
      { key: '/questions/ai-bank', label: 'AI题库' },
      { key: '/questions/ai-generated', label: 'AI生成题库' },
    ],
  },
  {
    key: '/resources',
    icon: <BookOutlined />,
    label: '课程与资源管理',
    children: [
      { key: '/resources/ai-explanation', label: 'AI生成知识点讲解' },
    ],
  },
  {
    key: '/review',
    icon: <SafetyOutlined />,
    label: '内容审核与质检',
  },
  {
    key: '/analytics',
    icon: <BarChartOutlined />,
    label: '学习数据分析',
    children: [
      { key: '/analytics/population', label: '普遍学习规律分析' },
      { key: '/analytics/personal', label: '个性化参数分析' },
      { key: '/analytics/marginal-value', label: '边际价值计算指标分析' },
      { key: '/analytics/diagnostic-priority', label: '测评任务优先级分析' },
      { key: '/analytics/targeted-practice', label: '针对新刷题算法指标' },
    ],
  },
  {
    key: '/users',
    icon: <TeamOutlined />,
    label: '用户与权限管理',
  },
  {
    key: '/system',
    icon: <SettingOutlined />,
    label: '系统配置',
    children: [
      { key: '/system/config', label: '运行设置' },
    ],
  },
]

export default function AdminLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const { token: { colorBgContainer, borderRadiusLG } } = theme.useToken()

  const selectedKeys = [location.pathname]
  const openKeys = menuItems
    .filter(item => item.children && location.pathname.startsWith(item.key))
    .map(item => item.key)

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        width={240}
        style={{ overflow: 'auto', height: '100vh', position: 'fixed', left: 0, top: 0, bottom: 0 }}
      >
        <div style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'flex-start',
          gap: collapsed ? 0 : 12,
          padding: collapsed ? 0 : '0 20px',
          color: '#fff',
          borderBottom: '1px solid rgba(255,255,255,0.1)',
          boxSizing: 'border-box',
        }}>
          <div style={{
            width: 36,
            height: 36,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}>
            <img
              src="/precision-learning-icon.png"
              alt="自适应学习系统"
              width={32}
              height={32}
              style={{ display: 'block', objectFit: 'contain' }}
            />
          </div>
          {!collapsed ? (
            <span style={{
              minWidth: 0,
              whiteSpace: 'nowrap',
              fontSize: 17,
              fontWeight: 600,
              lineHeight: '24px',
              letterSpacing: '0.2px',
            }}>
              自适应学习系统
            </span>
          ) : null}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={selectedKeys}
          defaultOpenKeys={openKeys}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout style={{ marginLeft: collapsed ? 80 : 240, transition: 'margin-left 0.2s' }}>
        <Header style={{ padding: '0 24px', background: colorBgContainer, borderBottom: '1px solid #f0f0f0' }}>
          <span style={{ fontSize: 16, fontWeight: 500 }}>后台管理系统</span>
        </Header>
        <Content style={{ margin: 16, padding: 24, background: colorBgContainer, borderRadius: borderRadiusLG, minHeight: 360 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
