import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/api';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Label } from '@/components/ui/Label';
import { Textarea } from '@/components/ui/Textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/Select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/Table';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/Dialog';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { format, parseISO } from 'date-fns';

interface Task {
  id: string;
  title: string;
  description: string | null;
  due_date: string;
  priority: 'low' | 'medium' | 'high' | 'urgent';
  status: 'todo' | 'doing' | 'done';
  project_id: string;
  assignee_id: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

interface Project { id: string; name: string; }
interface User { id: string; name: string; email: string; }

const PRIORITIES = ['low', 'medium', 'high', 'urgent'] as const;
const STATUSES = ['todo', 'doing', 'done'] as const;

function formatDate(dateStr: string) {
  try { return format(parseISO(dateStr), 'MMM d, yyyy'); } catch { return dateStr; }
}

export default function TaskPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [search, setSearch] = useState('');
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [formData, setFormData] = useState<Partial<Task>>({});
  const [projects, setProjects] = useState<Project[]>([]);
  const [users, setUsers] = useState<User[]>([]);

  const { data: tasksData, isLoading } = useQuery({
    queryKey: ['tasks', page, pageSize, search],
    queryFn: async () => {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (search) params.append('search', search);
      const res = await apiClient.get(`/tasks?${params.toString()}`);
      return res.data as { data: Task[]; total: number; page: number; page_size: number };
    },
  });

  const { data: projectsData } = useQuery({
    queryKey: ['projects'],
    queryFn: async () => (await apiClient.get('/projects?page_size=200')).data.data as Project[],
    onSuccess: setProjects,
  });

  const { data: usersData } = useQuery({
    queryKey: ['users'],
    queryFn: async () => (await apiClient.get('/users?page_size=200')).data.data as User[],
    onSuccess: setUsers,
  });

  const createMutation = useMutation({
    mutationFn: (data: Partial<Task>) => apiClient.post('/tasks', data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['tasks'] }); closeModal(); },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Task> }) => apiClient.patch(`/tasks/${id}`, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['tasks'] }); closeModal(); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.delete(`/tasks/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['tasks'] }); setDeletingId(null); },
  });

  const openCreateModal = () => {
    setEditingTask(null);
    setFormData({ title: '', description: '', due_date: '', priority: 'medium', status: 'todo', project_id: '', assignee_id: '' });
  };

  const openEditModal = (task: Task) => {
    setEditingTask(task);
    setFormData({
      title: task.title,
      description: task.description ?? '',
      due_date: task.due_date,
      priority: task.priority,
      status: task.status,
      project_id: task.project_id,
      assignee_id: task.assignee_id ?? '',
    });
  };

  const closeModal = () => { setEditingTask(null); setFormData({}); };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const payload = { ...formData, due_date: formData.due_date || undefined, assignee_id: formData.assignee_id || undefined };
    if (editingTask) updateMutation.mutate({ id: editingTask.id, data: payload });
    else createMutation.mutate(payload);
  };

  return (
    <div className="min-h-screen bg-stone-50 text-stone-900 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <Card className="bg-white">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-2xl font-bold bg-gradient-to-r from-amber-700 to-orange-600 bg-clip-text text-transparent">
              Tasks
            </CardTitle>
            <Dialog open={!!editingTask || formData.title !== undefined} onOpenChange={closeModal}>
              <DialogTrigger asChild>
                <Button className="bg-gradient-to-r from-amber-700 to-orange-600 hover:from-amber-800 hover:to-orange-700">
                  Create Task
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-2xl">
                <DialogHeader>
                  <DialogTitle>{editingTask ? 'Edit Task' : 'Create Task'}</DialogTitle>
                  <DialogDescription>Fill in the task details below.</DialogDescription>
                </DialogHeader>
                <form onSubmit={handleSubmit} className="space-y-4 p-4">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="md:col-span-2">
                      <Label htmlFor="title">Title *</Label>
                      <Input id="title" value={formData.title || ''} onChange={e => setFormData({ ...formData, title: e.target.value })} required />
                    </div>
                    <div className="md:col-span-2">
                      <Label htmlFor="description">Description</Label>
                      <Textarea id="description" value={formData.description || ''} onChange={e => setFormData({ ...formData, description: e.target.value })} rows={3} />
                    </div>
                    <div>
                      <Label htmlFor="due_date">Due Date</Label>
                      <Input id="due_date" type="date" value={formData.due_date || ''} onChange={e => setFormData({ ...formData, due_date: e.target.value })} />
                    </div>
                    <div>
                      <Label htmlFor="priority">Priority</Label>
                      <Select value={formData.priority || 'medium'} onValueChange={v => setFormData({ ...formData, priority: v as Task['priority'] })}>
                        <SelectTrigger id="priority"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {PRIORITIES.map(p => <SelectItem key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div>
                      <Label htmlFor="status">Status</Label>
                      <Select value={formData.status || 'todo'} onValueChange={v => setFormData({ ...formData, status: v as Task['status'] })}>
                        <SelectTrigger id="status"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {STATUSES.map(s => <SelectItem key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div>
                      <Label htmlFor="project_id">Project *</Label>
                      <Select value={formData.project_id || ''} onValueChange={v => setFormData({ ...formData, project_id: v })}>
                        <SelectTrigger id="project_id"><SelectValue placeholder="Select project" /></SelectTrigger>
                        <SelectContent>
                          {projects.map(p => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div>
                      <Label htmlFor="assignee_id">Assignee</Label>
                      <Select value={formData.assignee_id || ''} onValueChange={v => setFormData({ ...formData, assignee_id: v })}>
                        <SelectTrigger id="assignee_id"><SelectValue placeholder="Unassigned" /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="">Unassigned</SelectItem>
                          {users.map(u => <SelectItem key={u.id} value={u.id}>{u.name} ({u.email})</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <DialogFooter className="space-x-2">
                    <Button type="button" variant="outline" onClick={closeModal}>Cancel</Button>
                    <Button type="submit" className="bg-gradient-to-r from-amber-700 to-orange-600 hover:from-amber-800 hover:to-orange-700" disabled={createMutation.isPending || updateMutation.isPending}>
                      {createMutation.isPending || updateMutation.isPending ? 'Saving...' : 'Save'}
                    </Button>
                  </DialogFooter>
                </form>
              </DialogContent>
            </Dialog>
          </CardHeader>
          <CardContent>
            <div className="mb-4 flex gap-2">
              <Input placeholder="Search tasks..." value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} className="max-w-xs" />
              <Select value={String(pageSize)} onValueChange={v => { setPageSize(Number(v)); setPage(1); }}>
                <SelectTrigger className="w-[140px]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[10, 25, 50, 100].map(s => <SelectItem key={s} value={String(s)}>{s} per page</SelectItem>)}
                </SelectContent>
              </Select>
            </div>

            {isLoading ? (
              <div className="text-center py-8 text-stone-500">Loading tasks...</div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-stone-50">
                        <TableHead>Title</TableHead>
                        <TableHead>Due Date</TableHead>
                        <TableHead>Priority</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Project</TableHead>
                        <TableHead>Assignee</TableHead>
                        <TableHead className="text-right">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {tasksData?.data.length === 0 ? (
                        <TableRow><TableCell colSpan={7} className="text-center py-8 text-stone-500">No tasks found</TableCell></TableRow>
                      ) : (
                        tasksData?.data.map(task => (
                          <TableRow key={task.id} className="hover:bg-stone-50">
                            <TableCell className="font-medium">{task.title}</TableCell>
                            <TableCell>{formatDate(task.due_date)}</TableCell>
                            <TableCell>
                              <span className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                                task.priority === 'urgent' ? 'bg-red-100 text-red-800' :
                                task.priority === 'high' ? 'bg-orange-100 text-orange-800' :
                                task.priority === 'medium' ? 'bg-amber-100 text-amber-800' :
                                'bg-green-100 text-green-800'
                              }`}>{task.priority}</span>
                            </TableCell>
                            <TableCell>
                              <span className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                                task.status === 'done' ? 'bg-emerald-100 text-emerald-800' :
                                task.status === 'doing' ? 'bg-blue-100 text-blue-800' :
                                'bg-stone-100 text-stone-800'
                              }`}>{task.status}</span>
                            </TableCell>
                            <TableCell>{projects.find(p => p.id === task.project_id)?.name ?? task.project_id}</TableCell>
                            <TableCell>{users.find(u => u.id === task.assignee_id)?.name ?? 'Unassigned'}</TableCell>
                            <TableCell className="text-right">
                              <Popover>
                                <PopoverTrigger asChild>
                                  <Button variant="ghost" size="icon" className="text-stone-500 hover:text-stone-900">
                                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" /></svg>
                                  </Button>
                                </PopoverTrigger>
                                <PopoverContent side="bottom" align="end" className="w-48">
                                  <Button variant="ghost" className="w-full justify-start" onClick={() => { openEditModal(task); closeModal(); }}>Edit</Button>
                                  <AlertDialog>
                                    <AlertDialogTrigger asChild>
                                      <Button variant="ghost" className="w-full justify-start text-red-600 hover:text-red-700">Delete</Button>
                                    </AlertDialogTrigger>
                                    <AlertDialogContent>
                                      <AlertDialogHeader>
                                        <AlertDialogTitle>Delete Task</AlertDialogTitle>
                                        <AlertDialogDescription>Are you sure you want to delete "{task.title}"? This action cannot be undone.</AlertDialogDescription>
                                      </AlertDialogHeader>
                                      <AlertDialogFooter>
                                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                                        <AlertDialogAction onClick={() => deleteMutation.mutate(task.id)} className="bg-red-600 hover:bg-red-700">Delete</AlertDialogAction>
                                      </AlertDialogFooter>
                                    </AlertDialogContent>
                                  </AlertDialog>
                                </PopoverContent>
                              </Popover>
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </div>

                {tasksData && tasksData.total > pageSize && (
                  <div className="mt-4 flex items-center justify-between">
                    <span className="text-sm text-stone-600">
                      Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, tasksData.total)} of {tasksData.total}
                    </span>
                    <div className="flex gap-2">
                      <Button variant="outline" size="sm" onClick={() => setPage(p => p - 1)} disabled={page === 1}>Previous</Button>
                      <Button variant="outline" size="sm" onClick={() => setPage(p => p + 1)} disabled={page * pageSize >= tasksData.total}>Next</Button>
                    </div>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}