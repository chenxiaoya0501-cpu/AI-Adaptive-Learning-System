import { Layout, Menu, Dropdown, Space, Typography } from 'antd'
import {
  AimOutlined,
  UserOutlined,
  LogoutOutlined,
  HomeOutlined,
  FormOutlined,
  ShareAltOutlined,
  BranchesOutlined,
  ReadOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

const { Header, Content } = Layout

const items = [
  { key: '/', icon: <HomeOutlined />, label: '首页' },
  { key: '/goals', icon: <AimOutlined />, label: '目标' },
  { key: '/exam', icon: <FormOutlined />, label: '测评' },
  { key: '/learning-map', icon: <ShareAltOutlined />, label: '地图' },
  { key: '/learning-path', icon: <BranchesOutlined />, label: '路径' },
  { key: '/learn', icon: <ReadOutlined />, label: '学习' },
  { key: '/me', icon: <UserOutlined />, label: '我的' },
]

export default function StudentLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuth()

  const selected = /^\/goals\/[^/]+\/map$/.test(location.pathname)
    ? '/learning-map'
    : /^\/goals\/[^/]+\/path$/.test(location.pathname)
      ? '/learning-path'
      : items.find((i) => i.key !== '/' && location.pathname.startsWith(i.key))?.key ||
        (location.pathname === '/' ? '/' : location.pathname)
  const isLearningMap =
    location.pathname.startsWith('/learning-map') ||
    /^\/goals\/[^/]+\/(map|path)$/.test(location.pathname)
  const isCourseDetail = /^\/learn\/[^/]+\/[^/]+$/.test(location.pathname)

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 24,
          background: '#0f3d3e',
          padding: '0 24px',
        }}
      >
        <Space size={10} style={{ flexShrink: 0 }}>
          <img
            src="/precision-learning-icon.png"
            alt="自适应学习系统"
            width={34}
            height={34}
            style={{ display: 'block', objectFit: 'contain' }}
          />
          <Typography.Text strong style={{ color: '#fff', fontSize: 17, whiteSpace: 'nowrap' }}>
            自适应学习系统
          </Typography.Text>
        </Space>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[selected]}
          items={items}
          onClick={({ key }) => navigate(key)}
          style={{ flex: 1, background: 'transparent', minWidth: 0 }}
        />
        <Dropdown
          menu={{
            items: [
              { key: 'me', icon: <UserOutlined />, label: '我的', onClick: () => navigate('/me') },
              {
                key: 'logout',
                icon: <LogoutOutlined />,
                label: '退出登录',
                onClick: () => {
                  logout()
                  navigate('/login')
                },
              },
            ],
          }}
        >
          <Space style={{ color: '#fff', cursor: 'pointer' }}>
            <UserOutlined />
            <span>{user?.nickname || user?.email || user?.phone || '学生'}</span>
          </Space>
        </Dropdown>
      </Header>
      <Content
        style={{
          padding: isLearningMap || isCourseDetail ? '20px 28px' : 24,
          maxWidth: isLearningMap ? 1680 : isCourseDetail ? 1280 : 1100,
          width: '100%',
          margin: '0 auto',
        }}
      >
        <Outlet />
      </Content>
    </Layout>
  )
}
