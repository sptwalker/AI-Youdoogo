import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  groupChatApi,
  type Colleague,
  type DiscussionMember,
  type GroupChatApi,
  type MemberToAdd,
} from '../api'

interface UseChannelMembersOptions {
  channelId: string
  onMembershipChange(): void
  api?: GroupChatApi
}

export interface ChannelMembersState {
  members: DiscussionMember[]
  memberIds: string[]
  colleagues: Colleague[]
  loadColleagues(): Promise<void>
  addMembers(members: MemberToAdd[]): Promise<boolean>
  removeMember(member: DiscussionMember): Promise<void>
}

export function useChannelMembers({
  channelId,
  onMembershipChange,
  api = groupChatApi,
}: UseChannelMembersOptions): ChannelMembersState {
  const [members, setMembers] = useState<DiscussionMember[]>([])
  const [colleagues, setColleagues] = useState<Colleague[]>([])
  const activeChannelRef = useRef(channelId)
  activeChannelRef.current = channelId

  const refreshMembers = useCallback(async (signal?: AbortSignal) => {
    const requestedChannelId = channelId
    const items = await api.listMembers(requestedChannelId, { signal, silent: true })
    if (!signal?.aborted && activeChannelRef.current === requestedChannelId) setMembers(items)
  }, [api, channelId])

  useEffect(() => {
    const controller = new AbortController()
    void refreshMembers(controller.signal).catch(() => {})
    return () => controller.abort()
  }, [refreshMembers])

  const loadColleagues = useCallback(async () => {
    const requestedChannelId = channelId
    try {
      const items = await api.listColleagues()
      if (activeChannelRef.current === requestedChannelId) setColleagues(items)
    } catch {
      // Keep the picker available with the already loaded choices.
    }
  }, [api, channelId])

  const notifyAndRefresh = useCallback(() => {
    onMembershipChange()
    void refreshMembers().catch(() => {})
  }, [onMembershipChange, refreshMembers])

  const addSelectedMembers = useCallback(async (selected: MemberToAdd[]) => {
    if (selected.length === 0) return false
    await api.addMembers(channelId, selected)
    notifyAndRefresh()
    return true
  }, [api, channelId, notifyAndRefresh])

  const removeSelectedMember = useCallback(async (member: DiscussionMember) => {
    await api.removeMember(channelId, member.member_type, member.member_id)
    notifyAndRefresh()
  }, [api, channelId, notifyAndRefresh])

  const memberIds = useMemo(
    () => members.map((member) => member.member_id),
    [members],
  )

  return {
    members,
    memberIds,
    colleagues,
    loadColleagues,
    addMembers: addSelectedMembers,
    removeMember: removeSelectedMember,
  }
}
