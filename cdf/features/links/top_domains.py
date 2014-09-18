from itertools import groupby, ifilter, imap
import heapq
from cdf.features.links.helpers.predicates import (
    is_link,
    is_link_internal,
    is_follow_link
)
from cdf.utils.url import get_domain, get_second_level_domain
from cdf.utils.external_sort import external_sort
from cdf.features.links.streams import OutlinksRawStreamDef


class DomainLinkStats(object):
    """Stats of external outgoing links to a certain domain"""
    def __init__(self, name, follow, nofollow, follow_unique, sample_links=None):
        """Constructor
        :param name: the domain name
        :type name: str
        :param follow: the number of follow links to the domain
        :type follow: int
        :param nofollow: the number of nofollow links to the domain
        :type nofollow: int
        :param follow_unique: the number of unique follow links to the domain
        :type follow_unique: int
        :param sample_links: a list of sample link destination
                             (as a list of LinkDestination)
        :type sample_links: list
        """
        self.name = name
        self.follow = follow
        self.nofollow = nofollow
        self.follow_unique = follow_unique
        self.sample_links = sample_links or []

    def to_dict(self):
        return {
            'domain': self.name,
            'unique_follow_links': self.follow_unique,
            'follow_links': self.follow,
            'no_follow_links': self.nofollow,
            'samples': [
                sample_link.to_dict() for sample_link in
                sorted(self.sample_links, key=lambda x: (x.unique_links, x.url))
            ]
        }

    def __eq__(self, other):
        return self.to_dict() == other.to_dict()

    def __repr__(self):
        return "DomainLinkStats({})".format(self.to_dict())

def filter_external_outlinks(outlinks):
    """Filter outlinks stream for external, <a> links

    :param outlinks: stream of OutLinksRawStreamDef
    :return: external, <a> outlinks stream
    """
    mask_idx = OutlinksRawStreamDef.field_idx('bitmask')
    dest_idx = OutlinksRawStreamDef.field_idx('dst_url_id')
    type_idx = OutlinksRawStreamDef.field_idx('link_type')
    # filter <a> links
    filtered = ifilter(
        lambda l: is_link(l[type_idx]),
        outlinks
    )
    # filter external outgoing links
    filtered = ifilter(
        lambda l: not is_link_internal(
            l[mask_idx], l[dest_idx], is_bitmask=True),
        filtered
    )
    return filtered


def _group_links(link_stream, key):
    """A helper function to group elements of a outlink stream
    according to a generic criterion.
    It returns tuples (key_value, corresponding links)
    :param link_stream: the input outlink stream from OutlinksRawStreamDef
                        (should contains only outlinks,
                        no inlinks, no canonical)
    :param link_stream: iterable
    """
    #sort links by key function
    link_stream = external_sort(link_stream, key=key)
    #group by key function
    for key_value, link_group in groupby(link_stream, key=key):
        yield key_value, list(link_group)


def count_unique_links(external_outlinks):
    """Count the number of unique links in a set of external outlinks.
    i.e. if a link to B occurs twice in page A, it is counted only once.
    :param external_outlinks: the input stream of external outlinks
                              (based on OutlinksRawStreamDef)
    :type external_outlinks: iterable
    :rtype: int
    """
    #remove duplicate links
    id_index = OutlinksRawStreamDef.field_idx("id")
    external_url_index = OutlinksRawStreamDef.field_idx("external_url")
    external_outlinks = imap(
        lambda x: (x[id_index], x[external_url_index]),
        external_outlinks
    )
    result = len(set(external_outlinks))
    return result


def count_unique_follow_links(external_outlinks):
    """Count the number of unique follow links in a set of external outlinks.
    i.e. if a link to B occurs twice in page A, it is counted only once.
    :param external_outlinks: the input stream of external outlinks
                              (based on OutlinksRawStreamDef)
    :type external_outlinks: iterable
    :rtype: int
    """
    bitmask_index = OutlinksRawStreamDef.field_idx("bitmask")
    #compute number of unique follow links
    external_follow_outlinks = ifilter(
        lambda x: is_follow_link(x[bitmask_index], is_bitmask=True),
        external_outlinks
    )
    return count_unique_links(external_follow_outlinks)


def _compute_top_domains(external_outlinks, n, key):
    """A helper function to compute the top n domains given a custom criterion.
    For each destination domain the function counts the number of unique follow
    links that points to it and use this number to select the top n domains.
    The method returns a list of tuple (nb unique follow links, domain)
    Elements are sorted by decreasing number of unique follow links
    :param external_outlinks: the input stream of external outlinks
                              (based on OutlinksRawStreamDef)
    :type external_outlinks: iterable
    :param n: the maximum number of domains we want to return
    :type n: int
    :param key: the function that extracts the domain from an entry from
                external_outlinks.
    :type key: func
    :rtype: list
    """
    nb_samples = 100
    heap = []
    for domain, link_group in _group_links(external_outlinks, key):

        nb_unique_follow_links = count_unique_follow_links(link_group)

        if nb_unique_follow_links == 0:
            #we don't want to return domain with 0 occurrences.
            continue

        if len(heap) < n:
            domain_stats = compute_domain_stats((domain, link_group))
            domain_stats.sample_links = compute_sample_links(link_group, nb_samples)
            heapq.heappush(heap, (nb_unique_follow_links, domain_stats))
        else:
            min_value = heap[0][0]
            if nb_unique_follow_links < min_value:
                #avoid useless pushpop()
                continue
            domain_stats = compute_domain_stats((domain, link_group))
            domain_stats.sample_links = compute_sample_links(link_group, nb_samples)
            heapq.heappushpop(heap, (nb_unique_follow_links, domain_stats))
    #back to a list
    result = []
    while len(heap) != 0:
        nb_unique_follow_links, domain = heapq.heappop(heap)
        result.append((nb_unique_follow_links, domain))
    #sort by decreasing number of links
    result.reverse()
    return result


def compute_top_domains(external_outlinks, n):
    """A helper function to compute the top n domains.
    For each destination domain the function counts the number of unique follow
    links that points to it and use this number to select the top n domains.
    The method returns a list of tuple (nb unique follow links, domain)
    Elements are sorted by decreasing number of unique follow links
    :param external_outlinks: the input stream of external outlinks
                              (based on OutlinksRawStreamDef)
    :type external_outlinks: iterable
    :param n: the maximum number of domains we want to return
    :type n: int
    :param key: the function that extracts the domain from an entry from
                external_outlinks.
    :type key: func
    :rtype: list
    """
    external_url_idx = OutlinksRawStreamDef.field_idx("external_url")
    key = lambda x: get_domain(x[external_url_idx])
    return _compute_top_domains(external_outlinks, n, key)


def compute_top_second_level_domains(external_outlinks, n):
    """A helper function to compute the top n second level domains.
    The method is very similar to "compute_top_n_domains()" but it consider
    "doctissimo.fr" and "forum.doctissimo.fr" as the same domain
    while "compute_top_n_domains()" consider them as different.
    :param external_outlinks: the input stream of external outlinks
                              (based on OutlinksRawStreamDef)
    :type external_outlinks: iterable
    :param n: the maximum number of domains we want to return
    :type n: int
    :param key: the function that extracts the domain from an entry from
                external_outlinks.
    :type key: func
    :rtype: list
    """
    external_url_idx = OutlinksRawStreamDef.field_idx("external_url")
    key = lambda x: get_second_level_domain(x[external_url_idx])
    return _compute_top_domains(external_outlinks, n, key)


def compute_domain_stats(grouped_outlinks):
    """Compute full stats out of outlinks of a specific domain

    :param grouped_outlinks: grouped qualified outlinks of a certain domain
        eg: (domain_name, [link1, link2, ...])
    :type grouped_outlinks: tuple
    :return: stats of outlinks that target the domain
    :rtype: dict
    """
    # counters
    follow = 0
    nofollow = 0
    follow_unique = 0

    # indices
    mask_idx = OutlinksRawStreamDef.field_idx('bitmask')
    external_url_idx = OutlinksRawStreamDef.field_idx('external_url')
    src_id_idx = OutlinksRawStreamDef.field_idx('id')

    seen_urls = set()
    domain_name, links = grouped_outlinks
    for link in links:
        is_follow = is_follow_link(link[mask_idx], is_bitmask=True)
        dest_url = link[external_url_idx]
        src_id = link[src_id_idx]

        if is_follow:
            follow += 1
            if (src_id, dest_url) not in seen_urls:
                follow_unique += 1
            # add to seen set
            seen_urls.add((src_id, dest_url))
        else:
            nofollow += 1

    return DomainLinkStats(domain_name, follow, nofollow, follow_unique)


class LinkDestination(object):
    """A class to represent a link destination.
    The link destination is defined by :
        - its destination urls
        - the number of unique links that point to it
        - a sample of source urlids.
    """
    def __init__(self, destination_url, unique_links, sample_sources):
        """Constructor
        :param destination_url: the destination url
        :type: str
        :param unique_links: the number of unique links that point to
                             the destination url
        :type unique_links: int
        :param sample_sources: a list of sample source urlids.
        :type sample_source: list
        """
        self.url = destination_url
        self.unique_links = unique_links
        self.sample_sources = sample_sources

    def __eq__(self, other):
        return (
            self.url == other.url and
            self.unique_links == other.unique_links and
            self.sample_sources == other.sample_sources
        )

    def __repr__(self):
        return "{}: {}, {}".format(self.url,
                                   self.unique_links,
                                   self.sample_sources)

    def to_dict(self):
        """Return a dict representation of the object
        :rtype: dict
        """
        return {
            "url": self.url,
            "unique_links": self.unique_links,
            "sources": self.sample_sources
        }


def get_source_sample(external_outlinks, n):
    """Compute a list of n different sample source urlids
    from a set of external outlinks that point to the same url.
    :param external_outlinks: the input stream of external outlinks
                              (based on OutlinksRawStreamDef).
                              They all point to the same domain.
    :type external_outlinks: iterable
    :param n: the maximum number of sample links to return
    :type n: int
    :rtype: list
    """
    id_idx = OutlinksRawStreamDef.field_idx("id")
    source_urlids = set([x[id_idx] for x in external_outlinks])
    return heapq.nsmallest(n, source_urlids)


def compute_sample_links(external_outlinks, n):
    """Compute sample links from a set of external outlinks that point
    to the same domain.
    The method select the n most linked urls (via the number of unique links)
    For each of the most linked urls, it reports: the url, the number of unique
    links, 3 source urlids.
    The function returns a list of LinkDestination.
    :param external_outlinks: the input stream of external outlinks
                              (based on OutlinksRawStreamDef).
                              They all point to the same domain.
    :type external_outlinks: iterable
    :param n: the maximum number of sample links to return
    :type n: int
    :rtype: list
    """
    external_url_idx = OutlinksRawStreamDef.field_idx("external_url")
    external_outlinks = sorted(external_outlinks, key=lambda x: x[external_url_idx])
    heap = []
    for external_url, links in groupby(external_outlinks, key=lambda x: x[external_url_idx]):
        #transform iterator in list because we will need it more than once.
        links = list(links)
        nb_unique_links = count_unique_links(links)
        nb_source_samples = 3
        sample_sources = get_source_sample(links, nb_source_samples)
        link_sample = LinkDestination(external_url, nb_unique_links, sample_sources)
        if len(heap) < n:
            heapq.heappush(heap, (nb_unique_links, link_sample))
        else:
            heapq.heappushpop(heap, (nb_unique_links, link_sample))

    #back to a list
    result = []
    while len(heap) != 0:
        nb_unique_links, external_url = heapq.heappop(heap)
        result.append(external_url)
    #sort by decreasing number of links
    result.reverse()
    return result
