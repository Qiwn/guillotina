import logging

from guillotina import configure
from guillotina.api.service import Service
from guillotina.catalog.utils import reindex_in_future
from guillotina.component import query_utility
from guillotina.interfaces import ICatalogUtility
from guillotina.interfaces import IResource


logger = logging.getLogger('guillotina')


async def _search(context, request, query):
    search = query_utility(ICatalogUtility)
    if search is None:
        return {
            'items_count': 0,
            'member': []
        }

    return await search.query(context, query)


@configure.service(
    context=IResource, method='GET', permission='guillotina.SearchContent', name='@search',
    summary='Make search request',
    parameters=[],
    responses={
        "200": {
            "description": "Search results",
            "type": "object",
            "schema": {
                "$ref": "#/definitions/SearchResults"
            }
        }
    })
async def search_get(context, request):
    q = request.url.query.copy()
    return await _search(context, request, q)


@configure.service(
    context=IResource, method='POST',
    permission='guillotina.RawSearchContent', name='@search',
    summary='Make a complex search query',
    parameters=[{
        "name": "body",
        "in": "body",
        "schema": {
            "properties": {}
        }
    }],
    responses={
        "200": {
            "description": "Search results",
            "type": "object",
            "schema": {
                "$ref": "#/definitions/SearchResults"
            }
        }
    })
async def search_post(context, request):
    q = await request.json()
    return await _search(context, request, q)


@configure.service(
    context=IResource, method='POST',
    permission='guillotina.ReindexContent', name='@catalog-reindex',
    summary='Reindex entire container content',
    responses={
        "200": {
            "description": "Successfully reindexed content"
        }
    })
class CatalogReindex(Service):

    def __init__(self, context, request, security=False):
        super(CatalogReindex, self).__init__(context, request)
        self._security_reindex = security

    async def __call__(self):
        search = query_utility(ICatalogUtility)
        if search is not None:
            await search.reindex_all_content(self.context, self._security_reindex)
        return {}


@configure.service(
    context=IResource, method='POST',
    permission='guillotina.ReindexContent', name='@async-catalog-reindex',
    summary='Asynchronously reindex entire container content',
    responses={
        "200": {
            "description": "Successfully initiated reindexing"
        }
    })
class AsyncCatalogReindex(Service):

    def __init__(self, context, request, security=False):
        super(AsyncCatalogReindex, self).__init__(context, request)
        self._security_reindex = security

    async def __call__(self):
        reindex_in_future(self.context, False)
        return {}


@configure.service(
    context=IResource, method='POST',
    permission='guillotina.ManageCatalog', name='@catalog',
    summary='Initialize catalog',
    responses={
        "200": {
            "description": "Successfully initialized catalog"
        }
    })
async def catalog_post(context, request):
    search = query_utility(ICatalogUtility)
    await search.initialize_catalog(context)
    return {}


@configure.service(
    context=IResource, method='DELETE',
    permission='guillotina.ManageCatalog', name='@catalog',
    summary='Delete search catalog',
    responses={
        "200": {
            "description": "Successfully deleted catalog"
        }
    })
async def catalog_delete(context, request):
    search = query_utility(ICatalogUtility)
    await search.remove_catalog(context)
    return {}
