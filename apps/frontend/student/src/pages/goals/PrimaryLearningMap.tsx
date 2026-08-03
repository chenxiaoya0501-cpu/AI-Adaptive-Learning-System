import { Alert, Button, Empty, Spin } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { goalsApi } from '../../api/goals'

type LoadState = 'loading' | 'missing' | 'error'

type PrimaryGoalRedirectProps = {
  destination: 'map' | 'path'
}

export function PrimaryGoalRedirect({ destination }: PrimaryGoalRedirectProps) {
  const navigate = useNavigate()
  const [state, setState] = useState<LoadState>('loading')
  const resourceName = destination === 'map' ? '学习地图' : '学习路径'

  const loadPrimaryGoal = useCallback(async () => {
    setState('loading')
    try {
      const response = await goalsApi.primary()
      if (response.data) {
        const target =
          destination === 'map'
            ? `/learning-map/${response.data.id}`
            : `/goals/${response.data.id}/path`
        navigate(target, { replace: true })
        return
      }
      setState('missing')
    } catch {
      setState('error')
    }
  }, [destination, navigate])

  useEffect(() => {
    void loadPrimaryGoal()
  }, [loadPrimaryGoal])

  if (state === 'loading') {
    return (
      <div style={{ minHeight: 360, display: 'grid', placeItems: 'center' }}>
        <Spin size="large" tip={`正在打开主目标${resourceName}…`} />
      </div>
    )
  }

  if (state === 'missing') {
    return (
      <Empty description="当前还没有主目标，请先创建目标或将已有目标设为主目标">
        <Button type="primary" onClick={() => navigate('/goals')}>
          前往学习目标
        </Button>
      </Empty>
    )
  }

  return (
    <Alert
      type="error"
      showIcon
      message={`主目标${resourceName}加载失败`}
      description={`暂时无法打开${resourceName}，请检查网络后重试。`}
      action={<Button onClick={() => void loadPrimaryGoal()}>重新加载</Button>}
    />
  )
}

export default function PrimaryLearningMap() {
  return <PrimaryGoalRedirect destination="map" />
}
