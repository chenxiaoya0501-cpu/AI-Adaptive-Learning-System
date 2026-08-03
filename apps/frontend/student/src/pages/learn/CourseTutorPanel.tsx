import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Input, Spin } from 'antd'
import {
  BulbOutlined,
  DeleteOutlined,
  RobotOutlined,
  SendOutlined,
  UserOutlined,
} from '@ant-design/icons'

import {
  coursesApi,
  type Course,
  type CourseTutorTurn,
} from '../../api/courses'
import { MarkdownContent } from '../../components/MarkdownContent'

type TutorMessage = CourseTutorTurn & {
  id: string
  isGreeting?: boolean
}

const STARTER_QUESTIONS = [
  '能用更简单的话解释这个知识点吗？',
  '请举一个生活中的例子',
  '这个知识点最容易错在哪里？',
]

let messageSequence = 0

function messageId(role: CourseTutorTurn['role']) {
  messageSequence += 1
  return `${role}-${Date.now()}-${messageSequence}`
}

function initialMessages(kpName: string): TutorMessage[] {
  return [{
    id: messageId('assistant'),
    role: 'assistant',
    isGreeting: true,
    content: `我是本节课的 AI 助教。关于“${kpName}”哪里没听懂，可以随时问我。`,
  }]
}

function tutorErrorText(error: any) {
  return error?.response?.data?.detail || 'AI助教暂时没有响应，请稍后再试'
}

export function CourseTutorPanel({ course }: { course: Course }) {
  const [messages, setMessages] = useState<TutorMessage[]>(() => initialMessages(course.kp_name))
  const [suggestions, setSuggestions] = useState(STARTER_QUESTIONS)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState('')
  const messageEndRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    setMessages(initialMessages(course.kp_name))
    setSuggestions(STARTER_QUESTIONS)
    setQuestion('')
    setError('')
  }, [course.kp_id, course.kp_name])

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [messages, asking])

  const clearConversation = () => {
    setMessages(initialMessages(course.kp_name))
    setSuggestions(STARTER_QUESTIONS)
    setQuestion('')
    setError('')
  }

  const ask = async (presetQuestion?: string) => {
    const content = (presetQuestion ?? question).trim()
    if (!content || asking) return

    const history = messages
      .filter(message => !message.isGreeting)
      .slice(-8)
      .map(({ role, content: historyContent }) => ({ role, content: historyContent }))
    const studentMessage: TutorMessage = {
      id: messageId('user'),
      role: 'user',
      content,
    }

    setMessages(current => [...current, studentMessage])
    setQuestion('')
    setSuggestions([])
    setError('')
    setAsking(true)
    try {
      const result = await coursesApi.askTutor(course.path_id, course.kp_id, {
        question: content,
        history,
      })
      setMessages(current => [
        ...current,
        {
          id: messageId('assistant'),
          role: 'assistant',
          content: result.answer,
        },
      ])
      setSuggestions(result.suggested_questions.length
        ? result.suggested_questions
        : STARTER_QUESTIONS)
    } catch (requestError) {
      setError(tutorErrorText(requestError))
      setSuggestions(STARTER_QUESTIONS)
    } finally {
      setAsking(false)
    }
  }

  return (
    <aside className="course-tutor-panel" aria-label="AI实时答疑">
      <header className="course-tutor-header">
        <div className="course-tutor-avatar"><RobotOutlined /></div>
        <div>
          <strong>AI 实时答疑</strong>
          <span><i /> 正在学习：{course.kp_name}</span>
        </div>
        <Button
          type="text"
          size="small"
          icon={<DeleteOutlined />}
          aria-label="清空答疑记录"
          title="清空答疑记录"
          onClick={clearConversation}
        />
      </header>

      <div className="course-tutor-messages" aria-live="polite">
        {messages.map(message => (
          <div className={`course-tutor-message is-${message.role}`} key={message.id}>
            <span className="course-tutor-message-avatar">
              {message.role === 'assistant' ? <RobotOutlined /> : <UserOutlined />}
            </span>
            <div className="course-tutor-bubble">
              {message.role === 'assistant'
                ? <MarkdownContent content={message.content} />
                : message.content}
            </div>
          </div>
        ))}
        {asking && (
          <div className="course-tutor-message is-assistant">
            <span className="course-tutor-message-avatar"><RobotOutlined /></span>
            <div className="course-tutor-bubble course-tutor-thinking">
              <Spin size="small" /> 正在结合本节讲解为你分析…
            </div>
          </div>
        )}
        {error && <Alert type="error" showIcon message={error} />}
        <div ref={messageEndRef} />
      </div>

      <div className="course-tutor-suggestions">
        <span><BulbOutlined /> 你可以这样问</span>
        <div>
          {suggestions.map(item => (
            <button
              type="button"
              key={item}
              disabled={asking}
              onClick={() => void ask(item)}
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      <footer className="course-tutor-composer">
        <Input.TextArea
          value={question}
          maxLength={500}
          autoSize={{ minRows: 2, maxRows: 4 }}
          placeholder="输入没听懂的地方，Enter 发送…"
          disabled={asking}
          onChange={event => setQuestion(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void ask()
            }
          }}
        />
        <div>
          <span>Shift + Enter 换行</span>
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={asking}
            disabled={!question.trim()}
            onClick={() => void ask()}
          >
            发送
          </Button>
        </div>
        <small>AI回答仅用于辅助理解，重要结论请结合课程讲解核对。</small>
      </footer>
    </aside>
  )
}
