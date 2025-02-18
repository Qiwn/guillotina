import asyncio
import uuid
from functools import partial
from typing import Any
from typing import Callable
from typing import Coroutine
from typing import Optional
from typing import Union

from guillotina import task_vars
from guillotina.component import get_utility
from guillotina.exceptions import TransactionNotFound
from guillotina.interfaces import IAsyncJobPool
from guillotina.interfaces import IQueueUtility
from guillotina.interfaces import IView
from guillotina.profile import profilable
from guillotina.transactions import get_transaction
from guillotina.utils import get_current_request
from zope.interface import implementer


class ExecuteContext:
    '''
    Execution context object to allow you to run the function
    in different contexts.
    '''

    def __init__(self, func, *args, **kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def after_request(self, _name=None, _request=None):
        '''
        Execute after the request has successfully finished.

        :param _name: unique identifier to give in case you want to prevent duplicates
        :param _request: provide request object to prevent request lookup
        '''
        after_request(self.func, _name=_name, _request=_request, *self.args, **self.kwargs)

    def after_request_failed(self, _name=None, _request=None):
        '''
        Execute after the request has failed or errored.

        :param _name: unique identifier to give in case you want to prevent duplicates
        :param _request: provide request object to prevent request lookup
        '''
        after_request_failed(self.func, _name=_name, _request=_request, *self.args, **self.kwargs)

    def after_commit(self, _request=None):
        '''
        Execute after we commit to the database.

        :param _request: provide request object to prevent request lookup
        '''
        after_commit(self.func, _request=_request, *self.args, **self.kwargs)

    def before_commit(self, _request=None):
        '''
        Execute just before we commit to the database.

        :param _request: provide request object to prevent request lookup
        '''
        before_commit(self.func, _request=_request, *self.args, **self.kwargs)


@implementer(IView)
class GenerateQueueView:

    def __init__(self, func, request, args, kwargs):
        self.func = func
        self.request = request
        self.args = args
        self.kwargs = kwargs

    async def __call__(self):
        await self.func(*self.args, **self.kwargs)


def in_queue_with_func(func: Callable[..., Coroutine[Any, Any, Any]], *args,
                       _request=None, **kwargs) -> ExecuteContext:
    '''
    Execute function in the async queue.

    :param func: function to be queued
    :param _request: provide request object to prevent request lookup
    :param \\*args: arguments to call the func with
    :param \\**kwargs: keyword arguments to call the func with

    :rtype: ExecuteContext
    '''
    if _request is None:
        _request = get_current_request()
    view = GenerateQueueView(func, _request, args, kwargs)
    return in_queue(view)


def in_queue(view: Union[IView, GenerateQueueView]) -> ExecuteContext:
    '''
    Execute view-type object(context, request) in the async queue.

    :param view: view to be queued

    :rtype: ExecuteContext
    '''
    util = get_utility(IQueueUtility)
    return ExecuteContext(util.add, view)


async def __add_to_pool(func: Callable[..., Coroutine[Any, Any, Any]],
                        request, args, kwargs):
    # make add_job async
    util = get_utility(IAsyncJobPool)
    util.add_job(func, request=request, args=args, kwargs=kwargs)


def in_pool(func: Callable[..., Coroutine[Any, Any, Any]],
            *args, request=None, **kwargs) -> ExecuteContext:
    '''
    Execute function in the async pool.

    :param func: function to be queued
    :param _request: provide request object to prevent request lookup.
                     Provide if function be wrapped in database transaction.
    :param \\*args: arguments to call the func with
    :param \\**kwargs: keyword arguments to call the func with

    :rtype: ExecuteContext
    '''
    return ExecuteContext(__add_to_pool, func, request, args, kwargs)


def after_request(func: Callable[..., Coroutine[Any, Any, Any]],
                  *args, _name=None, _request=None, _scope='', **kwargs):
    '''
    Execute after the request has successfully finished.

    :param func: function to be queued
    :param _name: unique identifier to give in case you want to prevent duplicates
    :param _scope: customize scope of after commit to run for instead of default(successful request)
    :param \\*args: arguments to call the func with
    :param \\**kwargs: keyword arguments to call the func with
    '''
    if _name is None:
        _name = uuid.uuid4().hex
    kwargs.pop('_request', None)  # b/w compat pop unused param
    add_future(_name, func, scope=_scope, args=args, kwargs=kwargs)


def after_request_failed(func: Callable[..., Coroutine[Any, Any, Any]],
                         *args, _name=None, _request=None, **kwargs):
    '''
    Execute after the request has failed or errored.

    :param func: function to be queued
    :param \\*args: arguments to call the func with
    :param \\**kwargs: keyword arguments to call the func with
    '''
    kwargs.pop('_request', None)  # b/w compat pop unused param
    after_request(func, _name=_name, _scope='failed', *args, **kwargs)


def after_commit(func: Callable, *args, **kwargs):
    '''
    Execute a commit to the database.

    :param func: function to be queued
    :param \\*args: arguments to call the func with
    :param \\**kwargs: keyword arguments to call the func with
    '''
    kwargs.pop('_request', None)  # b/w compat pop unused param
    txn = get_transaction()
    if txn is not None:
        txn.add_after_commit_hook(func, args=args, kwargs=kwargs)
    else:
        raise TransactionNotFound('Could not find transaction to run job with')


def before_commit(func: Callable[..., Coroutine[Any, Any, Any]],
                  *args, **kwargs):
    '''
    Execute before a commit to the database.

    :param func: function to be queued
    :param _request: provide request object to prevent request lookup
    :param \\*args: arguments to call the func with
    :param \\**kwargs: keyword arguments to call the func with
    '''
    kwargs.pop('_request', None)  # b/w compat pop unused param
    txn = get_transaction()
    if txn is not None:
        txn.add_before_commit_hook(func, args=args, kwargs=kwargs)
    else:
        raise TransactionNotFound('Could not find transaction to run job with')


def add_future(name: str, fut: Callable[..., Coroutine[Any, Any, Any]],
               scope: str='', args=None, kwargs=None):
    '''
    Register a future to be executed after the task has finished.

    :param name: name of future
    :param fut: future to execute after task
    :param scope: group the futures to execute different groupings together
    :param args: arguments to execute future with
    :param kwargs: kwargs to execute future with
    '''
    futures = task_vars.futures.get()
    if futures is None:
        futures = {}
        task_vars.futures.set(futures)
        task = asyncio.current_task()
        if task is not None and scope == '':
            task.add_done_callback(partial(execute_futures, scope, futures))
    if scope not in futures:
        futures[scope] = {}
    futures[scope][name] = {
        'fut': fut,
        'args': args,
        'kwargs': kwargs
    }


def get_future(name: str, scope: str=''):
    '''
    Get a registered future

    :param name: scoped futures to execute. Leave default for normal behavior
    :param scope: scope name the future was registered for
    '''
    futures = task_vars.futures.get() or {}
    try:
        if scope not in futures:
            return
        return futures[scope][name]['fut']
    except (AttributeError, KeyError):
        return


@profilable
def execute_futures(scope: str='', futures=None, task=None) -> Optional[asyncio.Task]:
    '''
    Execute all the registered futures in a new task

    :param scope: scoped futures to execute. Leave default for normal behavior
    '''
    if futures is None:
        futures = task_vars.futures.get() or {}
        if scope not in futures:
            return None
    found = []
    for fut_data in futures[scope].values():
        fut = fut_data['fut']
        if not asyncio.iscoroutine(fut):
            fut = fut(*fut_data.get('args') or [], **fut_data.get('kwargs') or {})
        found.append(fut)
    futures[scope] = {}
    if len(found) > 0:
        task = asyncio.ensure_future(asyncio.gather(*found))
        return task
    return None


def clear_futures(self):
    futures = task_vars.futures.get() or {}
    futures.clear()

    futures = {}
    task_vars.futures.set(futures)
