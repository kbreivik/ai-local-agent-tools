/**
 * TaskContext — shared agent task string so AgentTaskBar, CommandPanel,
 * and ChoiceBar all read/write the same value.
 */
import { createContext, useContext, useState, useCallback } from 'react'

const TaskContext = createContext(null)

export function TaskProvider({ children }) {
  const [task, setTask] = useState('')

  const prefillTask = useCallback((text) => setTask(text), [])

  return (
    <TaskContext.Provider value={{ task, setTask, prefillTask }}>
      {children}
    </TaskContext.Provider>
  )
}

export function useTask() {
  const ctx = useContext(TaskContext)
  if (!ctx) throw new Error('useTask must be used inside TaskProvider')
  return ctx
}
