"""
This script is used to update rankings and list with latest article and image counts.

==  List of accepted arguments  =====

-saveconfig:filename        Settings will be dumped to given file (in JSON format)

-loadconfig:filename        Settings will be loaded from given file.
                            User then will be given an option to save these setting on wiki
                            (sysop account needed - MediaWiki namespace)

-revisionday:YYYY-MM-DD     Use revision made on that day as a reference for changes on wiki rankings
                            (or next one right after that date)

==  FLAGS  ==========================

-forcelist        Ignore edit restriction for list

-forceranking     Ignore edit restriction for rankings

-clean            Don't add changes in wiki's place in rankings
                  (ie. wiki's gone up, down, is new or didn't change place)

-listonly         Only list of wikis will be updated.
                  Rankings won't be changed at all.

-saveold          Old wiki names will be saved as Displayed name parameter
                  if different then current wiki name.

-simulate         Just a reminder it's usefull here ;)

==  Exit codes  =====================

0       On success

1       Missing config

2       Missing list page

3       Run out of revisions to parse on config[pages][list] page

4       Edit restricted

100     On KeyboardInterrupt

"""
#
# Distributed under the terms of the CC-BY-NC 3.0 license.
# License summary: http://creativecommons.org/licenses/by-nc/3.0/
# Full legal code: http://creativecommons.org/licenses/by-nc/3.0/legalcode
#
#

import wikipedia as pywikibot
import userlib
import sys, re, datetime
import urllib2, json, codecs

# Set this and it'll work on that wiki regardles of what wiki is set as default in user-config.py
# You can still override this with -family and -lang switches

force_family = 'community'
force_lang = 'pl'

# And rest of the config is stored on the wiki
# Mediawiki:Ranking-bot-pages

# Default config structure - don't edit settings here 
config = {
    'languages': None,
    'pages': {
        'list': None,
        'ranking_main_article': None,
        'ranking_main_image': None,
        'ranking_category_article': None,
        'ranking_category_image': None,
    },
    'limits': {
        'main_article': None,
        'main_image': None,
        'category_article': None,
        'category_image': None,
    },
    'templates': {
        'list_record': None,
        'category_record': None,
        'column': None,
        'ranking_record': None,
    },
    'tags': {
        'ranking_columns': None,
        'list': None,
        'talk': None,
        'categories': None,
    },
    'msg': {},
    'allowed_groups': [],
    'allowed_users': [],
    'admin_active_days': 60,
    'edit_restriction': {
        'list': {
            'once': None,
            'days': None,
        },
        'ranking': {
            'once': None,
            'days': None,
        },
    }
}

def exit(key):
    global args
    code = {
        'OK': 0,
        'NoConfig': 1,
        'NoList': 2,
        'OutOfRevisions': 3,
        'EditRestricted': 4,
        'KeyboardInterrupt': 100,
    }[key]
    try:
        if args['extended'] and code: pywikibot.output('\03{lightgreen}Terminating script\03{default} - Exit code: \03{lightgreen}%d\03{default} [%s]' % (code, key))
    except NameError: return code
        
    pywikibot.stopme()
    sys.exit(code)
    return code
def main():
    initialize()
    global site, config, args
    
    if args['extended']: pywikibot.output('\n\03{lightgreen}=================================================== \03{lightyellow} Initialization COMPLETE \03{lightgreen} ====================================================\03{default}')
    
    list = pywikibot.Page(site, config['pages']['list'])
    listtalk = list.toggleTalkPage()
    
    if not list.exists():
        pywikibot.output('\n\n\03{lightred}FATAL ERROR:\03{default} List page (\03{lightaqua}%s\03{default}) does not exits.' % list.title())
        return exit('NoList')
    
    if args['forcelist']: list_restriction = True
    else: list_restriction = check_edit_restriction(list, 'list')
    
    if not list_restriction:
        pywikibot.output('\n\n\03{lightred}Edit restricted:\03{default} Cannot continue due to edit restriction on page \03{lightaqua}%s\03{default}' % list.title())
        if pywikibot.simulate:
            pywikibot.output("\n\03{lightgreen}Simulation enabed\03{default} - continuing regardless");
        else:
            return exit('EditRestricted')
    
    preprocess_list(list)
    process_list_talk(listtalk)
    process_list(list)
    if args['extended']: pywikibot.output('\n\03{lightgreen}=========================================================== \03{lightyellow} List DONE \03{lightgreen} ===========================================================\03{default}')
    start_rankings()
    if args['extended']: pywikibot.output('\n\03{lightgreen}========================================================= \03{lightyellow} Rankings DONE \03{lightgreen} =========================================================\03{default}')
    
    run_put_queue()
def get_ranking_cols(page):
    global args, config
    
    if args['revisionday'] != None:
        history = page.getVersionHistory(forceReload = True, getAll = True)
        
        for rev in history:
            edit_time = datetime.datetime.strptime(rev[1], u'%Y-%m-%dT%H:%M:%SZ')
            if edit_time.date() < args['revisionday']: break
            lasttime = edit_time
            lastrev = rev
        text = page.getOldVersion(lastrev[0])
        pywikibot.output('Using revision \03{lightgreen}#%d\03{default} made by \03{lightyellow}%s\03{default} on \03{lightaqua}%s\03{default} for ranking position reference' % (lastrev[0], lastrev[2], lasttime))
    else:
        text = page.getOldVersion(page.latestRevision())
        
    cols = []
    tags = config['tags']['ranking_columns']
    for tag in tags:
        try:
            col = get_between(text, tag)
            cols.append(col)
        except TagsNotFound:
            break
    
    return cols
def check_edit_restriction(page, opt):
    global site, current_time, args
    history = page.getVersionHistory(forceReload = True, getAll = True)
    pywikibot.output("\03{lightyellow}Checking edit restriction for\03{default}: \03{lightaqua}%s\03{default}" % (page.title()))
    
    comment = __({'list':'list_update_summary','ranking':'ranking_update_summary'}[opt])
    index = 0
    while True:
        try:
            rev = history[index]
            summary = rev[3]
            if summary != comment: raise SkippedRevision(rev)
                
            edit_time = datetime.datetime.strptime(rev[1], u'%Y-%m-%dT%H:%M:%SZ')
            
            if args['extended']:
                pywikibot.output("Last edit by a robot made on %s" % (edit_time.isoformat(' ')))
            
            try:
                return compare_dates(edit_time, opt)
            except EditRestrict, e:
                pywikibot.output("\03{lightaqua}%s\03{default}: %s" % (page.title(), e.val))
                return False
        except SkippedRevision, e:
            index += 1
        except IndexError:
            return True
    return True
def compare_dates(edit_time, opt):
    global current_time, config, args
    settings = config['edit_restriction'][opt]
    
    if settings['once'] == 'a day':
        if current_time.isocalendar()[2] not in settings['days']: raise EditRestrict('Edit cannot be made on that day: %d' % current_time.isocalendar()[2])
        if current_time.timetuple()[0:3] == edit_time.timetuple()[0:3]: raise EditRestrict('Page has been edited today: %d-%d-%d' % current_time.timetuple()[0:3])
        return True
    elif settings['once'] == 'a week':
        if current_time.isocalendar()[2] not in settings['days']: raise EditRestrict('Edit cannot be made on that day: %d' % current_time.isocalendar()[2])
        if current_time.isocalendar()[1] == edit_time.isocalendar()[1]: raise EditRestrict('Page has been edited this week: %d' % current_time.isocalendar()[1])
        return True
    elif settings['once'] == '2 weeks':
        if current_time.isocalendar()[2] not in settings['days']: raise EditRestrict('Edit cannot be made on that day: %d' % current_time.isocalendar()[2])
        if current_time.isocalendar()[1] == edit_time.isocalendar()[1]: raise EditRestrict('Page has been edited this week: %d' % current_time.isocalendar()[1])
        if current_time.isocalendar()[1]-1 == edit_time.isocalendar()[1]: raise EditRestrict('Page has been edited last week: %d' % current_time.isocalendar()[1])
        return True
    return False
def process_list_talk(page):
    global site, config, args, msg, new_wikis, on_the_list, all_cats
    pywikibot.output('\n\03{lightyellow}Processing page:\03{default} \03{lightaqua}%s\03{default}' % page.title())
    old_text = page.getOldVersion(page.latestRevision())
    
    new_wikis = []
    lines = get_between(old_text, config['tags']['talk'])
    lines = lines.replace('\r','').strip().split('\n')
    
    new_lines = []
    all = []
    for i, line in enumerate(lines):
        lines[i] = pywikibot.replaceExcept(lines[i], ur"^\s+|\s+$", "",[])
        lines[i] = pywikibot.replaceExcept(lines[i], ur"\*\s*\[\[w:c:(.*?)\|(.*?)\]\]\s*-?\s*(.*)\s*", ur"{} \1 | \2 | \3",[])
        lines[i] = pywikibot.replaceExcept(lines[i], ur"\*\s*\[\[w:c:(.*?)\]\]\s*-?\s*(.*)\s*", ur"{} \1 |  | \2",[])
        lines[i] = pywikibot.replaceExcept(lines[i], ur"\*\s*\[http:\/\/(.*?)\.wikia.com\/?\S*\s*(.*?)\]\s*-?\s*(.*)\s*", ur"{} \1 | \2 | \3",[])
        lines[i] = pywikibot.replaceExcept(lines[i], ur"\* *http:\/\/(www\.)(.*?)\.wikia.com\/?\S*\s*-?\s*(.*)\s*", ur"{} \1 |  | \2",[])
        
        if not lines[i].startswith("{}"):
            new_lines.append(lines[i])
            continue
        
        fields = lines[i][3:].split("|")
        
        fields[0] = fields[0].strip()
        fields[1] = fields[1].strip()
        fields[2] = fields[2].strip()
        
        try: info = get_wiki_info(fields[0])
        except JSONError: continue
        except InvalidWiki:
            if not fields[1]: fields[1] = fields[0]
            new_lines.append('* <s>[[w:c:%s|%s]]</s> - %s' % (fields[0], fields[1], __('no_wiki')))
            continue
        
        if info['wikia_code'] in all:
            continue
        
        if info['wikia_code'] in on_the_list:
            new_lines.append('* <s>[[w:c:%s|%s]]</s> - %s' % (info['wikia_code'], info['sitename'], __('on_the_list')))
            continue
        
        if info['lang'] not in config['languages']:
            new_lines.append('* <s>[[w:c:%s|%s]]</s> - %s' % (info['wikia_code'], info['sitename'], (__('wrong_language') % {'languages':', '.join(config['languages']),'lang':info['lang']})))
            continue
        
        categories = []
        if fields[2]:
            cats = fields[2].split(',')
            for cat in cats:
                cat = cat.lower().strip()
                if not cat: continue
                if cat not in all_cats: continue
                categories.append(cat)
        lines[i] = '* <s>[[w:c:%s|%s]]</s>' % (info['wikia_code'], info['sitename'])
        all.append(info['wikia_code'])
        new_lines.append(lines[i])
        new_wikis.append((info['wikia_code'],info['sitename'],categories))
    del lines
    
    new_lines, all, new_rest = find_lazies(page, old_text[old_text.find(config['tags']['talk'][1]):], new_lines, all)
    
    new_lines = '\n'.join(new_lines)
    new_text = put_between(old_text[:old_text.find(config['tags']['talk'][1])] + new_rest, config['tags']['talk'], "\n%s\n\n" % new_lines);
    
    old_text = old_text.strip()
    new_text = new_text.strip()
    
    queue_put(page, new_text, old_text = old_text, comment = __('talk_update_summary'))

def strike_lazies(text, span_list):
    span_list = reversed(span_list)
    for start, end in span_list:
        text = '%s<span>%s</span>%s' % (text[:start], text[start:end], text[end:])
    return text
        
def find_lazies(page, text, new_lines, all):
    global site, config, args, msg, new_wikis, on_the_list
    from httplib import InvalidURL as httplib_InvalidURL
    
    if args['extended']: pywikibot.output('\03{lightyellow}Scanning rest of the talk page for links\03{default}')

    strikes = get_all_strikes('\n'.join(new_lines))
    lazies = []
    
    patterns = [
        '[^\>^\[^\]]\s*(?P<match>http:\/\/(www\.)?(?P<code>.*?)\.wikia\.com[\S^\[^\]]*)\s*[^\<^\[^\]]',
        '[^\>]\s*(?P<match>\[http:\/\/(www\.)?(?P<code>.*?)\.wikia\.com[\S^\[^\]]*\s*[^\[^\]]*\])\s*[^\<]',
        '[^\>]\s*(?P<match>\[\[w:c:(?P<code>.*?)(\|.*?)?\]\])\s*[^\<]',
    ]
    pattern = re.compile('[^\>^\]]\s*http:\/\/(www\.)?(.*?)\.wikia\.com\s*[^\<]', re.I)
    old_text = text
    for pattern in patterns:
        rx = re.compile(pattern, re.I)
        iter = rx.finditer(text)
        strike = []
        while True:
            try: match = iter.next()
            except StopIteration: break
            else:
                lazies.append(match.group('code').strip())
                strike.append(match.span('match'))
        text = strike_lazies(text, strike)
    
    for rec in lazies:
        if rec in strikes: continue
        if rec in all: continue
        if rec in on_the_list: continue
        try: info = get_wiki_info(rec)
        except JSONError: continue
        except InvalidWiki: continue
        except httplib_InvalidURL: continue
        else:
            if info['wikia_code'] in all: continue
            if info['wikia_code'] in on_the_list: continue
            if info['lang'] not in config['languages']: continue
            new_lines.append('* <s>[[w:c:%(wikia_code)s|%(sitename)s]]</s>' % info)
            all.append(rec)
            new_wikis.append((info['wikia_code'],info['sitename'],[]))
    return (new_lines, all, text)

def start_rankings():
    global site, config, args, wikis, all_cats
    
    main_article = pywikibot.Page(site, config['pages']['ranking_main_article'])
    main_image = pywikibot.Page(site, config['pages']['ranking_main_image'])
    
    process_ranking(main_article)
    process_ranking(main_image, image=True)
    
    for cat in all_cats:
        pywikibot.output('')
        cat_article = pywikibot.Page(site, config['pages']['ranking_category_article'] % cat)
        cat_image = pywikibot.Page(site, config['pages']['ranking_category_image'] % cat)
        process_ranking(cat_article, cat=cat)
        process_ranking(cat_image, cat=cat, image=True)
    
    return
def process_ranking(page, cat=None, image=False):
    global site, config, args, wikis
    pywikibot.output('\n\03{lightyellow}Processing \03{lightgreen}%s\03{lightyellow} ranking by\03{lightpurple} %s\03{default}:  \03{lightaqua}%s\03{default}' % ( ('%s\03{lightyellow} category'%cat,'main')[cat==None], ('article','image')[image], page.title()))
    
    if not page.exists():
        pywikibot.output('\03{lightyellow}Page not found\03{default}: skipping this ranking')
        return
    
    if args['forceranking']: edit_restrict = True
    else: edit_restrict = check_edit_restriction(page, 'ranking');
    if not edit_restrict:
        pywikibot.output('\03{lightyellow}Edit restricted\03{default}: skipping this ranking')
        return
    
    cols = get_ranking_cols(page)
    
    col_count = len(cols)
    if col_count == 0:
        pywikibot.output('\03{lightyellow}Columns not found\03{default}: skipping this ranking')
        return
        
    if args['clean']: old_ranking = None
    else: old_ranking = get_old_ranking('\n'.join(cols))
    
    ranklist=[]
    
    if image: key = 'image'
    else: key = 'article'
        
    if cat==None:
        limit = config['limits']['main_'+key]
    else:
        limit = config['limits']['category_'+key]
        cat = cat.lower()
    
    key = key+'s'
    
    for wiki in wikis:
        if wiki['users'] == 0 or wiki[key] < limit: continue
        if cat!=None and cat not in wiki['categories']: continue
        
        if wiki['display']: name = wiki['display']
        else: name = wiki['name']
        
        ranklist.append({
            'code': wiki['code'],
            'name': name,
            'count': wiki[key]
        })
    
    rendered = render_ranking(ranklist, old_ranking = old_ranking)
    rendered = chunkIt(rendered, col_count)
    
    tags = config['tags']['ranking_columns']
    
    old_text = page.getOldVersion(page.latestRevision())
    new_text = old_text
    for i, rend in enumerate(rendered):
        rend = '\n'.join(rend)
        new_text = put_between(new_text, tags[i], '\n%s\n' % rend)
    
    new_text = pywikibot.replaceExcept(new_text, ur'<span (.*?)id="data"(.*?)>.*?</span>', r'<span \1id="data"\2>{{subst:#time:j xg Y}}</span>',[])
    new_text = pywikibot.replaceExcept(new_text, ur'<span (.*?)id="licznik"(.*?)>.*?</span>', (r'<span \1id="licznik"\2>%i</span>'%(len(ranklist))),[])
    
    queue_put(page, new_text, old_text = old_text, comment = __('ranking_update_summary'))
    
def render_ranking(wikis, old_ranking = None):
    global args
    qs(wikis, 'count')
    rend = []
    template = prepare_template('ranking_record')
    
    last_count = 0
    place = 1
    for wiki in reversed(wikis):
        code = wiki['code']
        if place == 1: wiki['place'] = place
        else:
            if wiki['count'] == last_count: wiki['place'] = ''
            else: wiki['place'] = place
        
        if old_ranking == None: wiki['move'] = ''
        else:
            if code not in old_ranking:     wiki['move'] = '**'
            elif old_ranking[code] > place: wiki['move'] = '++'
            elif old_ranking[code] < place: wiki['move'] = '--'
            else:                           wiki['move'] = '//'
                
        wiki['place'] = '%-3s' % wiki['place']
        wiki['count'] = '%7s' % wiki['count']
        rend.append(template % wiki)
        place += 1
        last_count = wiki['count']
    return rend
def get_old_ranking(text):
    ranking = {}
    basic = re.compile("\{\{\s*%s(.*?)\}\}"%re.escape(config['templates']['ranking_record'][0]), re.S)
    last_place = 1
    iter = basic.finditer(text)
    while True:
        try: match = iter.next().group(0)
        except StopIteration: break
        except AttributeError: continue
        else:
            info = template_params(match, 'ranking_record')
            info['place'] = info['place'].replace('.','')
            
            info['code'] = pywikibot.replaceExcept(info['code'], r'\[\[w:c:', r'', [])
            if not info['place']: info['place'] = last_place
            
            last_place = info['place'] = int(info['place'])
            ranking[info['code']] = info['place']
    return ranking
def chunkIt(seq, num):
    l = len(seq)
    avg = len(seq) / float(num)
    out = []
    last = 0.0
    while last < len(seq):
        out.append([l-int(last + avg),l-int(last)])
        last += avg
    new = []
    for x in reversed(out):
        new.append(seq[x[0]:x[1]])
    return new
def preprocess_list(page):
    global site, config, args, msg, on_the_list, old_list_text, wikis
    pywikibot.output('\n\03{lightyellow}Processing page:\03{default} \03{lightaqua}%s\03{default}' % page.title())
    index = 0
    
    history = page.getVersionHistory(forceReload = True, getAll = True)
    while True:
        try:
            rev = history[index]
            if not allowed_edit(rev[2]): raise SkippedRevision(rev)
            pywikibot.output("Processing revision \03{lightgreen}#%d\03{default} made by \03{lightyellow}%s\03{default}" % (rev[0], rev[2]))
            old_list_text = page.getOldVersion(rev[0])
            return process_list_revision(old_list_text)
        except SkippedRevision, e:
            if e.err: pywikibot.output("\03{lightpurple}Skipping\03{default} revision \03{lightgreen}#%d\03{default} made by \03{lightyellow}%s\03{default} - revision produced an error: %s" % (e.rev[0], e.rev[2], e.err))
            else: pywikibot.output("\03{lightpurple}Skipping\03{default} revision \03{lightgreen}#%d\03{default} made by \03{lightyellow}%s\03{default} - user not allowed to edit that page" % (rev[0], rev[2]))
            index += 1
        except IndexError:
            pywikibot.output('\n\n\03{lightred}FATAL ERROR:\03{default} Script has run out of revisions for \03{lightaqua}%s\03{default}' % page.title())
            return exit('OutOfRevisions')
            break
    
def process_list_revision(text):
    global site, config, args, msg, on_the_list, old_list_text, wikis, all_cats
        
    list = get_between(text, config['tags']['categories'])
    basic = re.compile("\{\{\s*%s(.*?)\}\}"%re.escape(config['templates']['category_record'][0]), re.S)
    all_cats = []
    iter = basic.finditer(list)
    while True:
        try: match = iter.next().group(0)
        except StopIteration: break
        except AttributeError: continue
        else:
            try:
                info = template_params(match, 'category_record')
                all_cats.append(info['name'].lower().strip())
            except AttributeError: continue
            except KeyError: continue
    
    list = get_between(text, config['tags']['list'])
    basic = re.compile("\{\{\s*%s(.*?)\}\}"%re.escape(config['templates']['list_record'][0]), re.S)
    count = 0
    on_the_list = []
    wikis = []
    iter = basic.finditer(list)
    while True:
        try: match = iter.next().group(0)
        except StopIteration: break
        except AttributeError: continue
        else:
            try:
                count += 1
                info = template_params(match, 'list_record')
                if 'code' not in info:
                    match = re.compile('http:\/\/(www\.)?(.*?)\.wikia\.com', re.I).search(info['address'])
                    info['code'] = match.group(2).strip()
                    
                cats = []
                if 'categories' in info:
                    info['categories'] = info['categories'].split(',')
                    for cat in info['categories']:
                        cat = cat.lower().strip()
                        if not cat: continue
                        if cat not in all_cats: continue
                        cats.append(cat)
                sorted(cats)
                info['categories'] = cats
                
                wikis.append(info)
                on_the_list.append(info['code'])
            except AttributeError: continue
            except KeyError: continue
    if count and len(wikis) == 0: raise SkippedRevision(rev, 'found %s entries but none yielded any resutlts' % count)
def process_list(page):
    global site, config, args, old_list_text, wikis, msg, new_wikis, all_cats
    
    pywikibot.output('\n\03{lightyellow}Processing page:\03{default} \03{lightaqua}%s\03{default}' % page.title())
    cats = parse_categories(get_between(old_list_text, config['tags']['categories']))
    
    lens = {
        'name':0,
        'code':0,
        'cats':0,
        'art':8,
        'img':6,
        'usr':5,
        'adm':6,
        'catname':0,
    }
    for wiki in new_wikis:
        code, name, catz = wiki
        lens['name'] = max(lens['name'], len(name))
        lens['code'] = max(lens['code'], len(code))
        lens['cats'] = max(lens['cats'], len(', '.join(catz)))
    for wiki in wikis:
        lens['name'] = max(lens['name'], len(wiki['name']))
        lens['code'] = max(lens['code'], len(wiki['code']))
        if type(wiki.setdefault('categories',[])) != list:
            wiki['categories'] = [wiki['categories']]
        lens['cats'] = max(lens['cats'], len(', '.join(wiki.setdefault('categories',[]))))
        lens['art'] = max(lens['art'], len(u"%s" % wiki['articles']))
        lens['img'] = max(lens['img'], len(u"%s" % wiki['images']))
        lens['usr'] = max(lens['usr'], len(u"%s" % wiki['users']))
        lens['adm'] = max(lens['adm'], len(u"%s" % wiki['admins']))
        wiki['articles'] = 0
        wiki['images'] = 0
        wiki['users'] = 0
        wiki['admins'] = 0
    
    the_list = []
    args['extended'] = False
    console_table(['Name','*','Code','Categories','Articles','Images','Users','Admins'], widths = [lens['name'],1,lens['code'],lens['cats'],lens['art'],lens['img'],lens['usr'],lens['adm']])
    
    for wiki in wikis:
        comment = ''
        try:
            data = get_wiki_statinfo(wiki['code'])
            admins = get_wiki_admins(wiki['code'], active=True)
        except InvalidWiki, e:
            comment = '\03{lightred}DELETE\03{default} - %s' % ('wiki not found','wiki closed')[e.closed]
            console_row([wiki['display'] or wiki['name'],' ',wiki['code'],'','','','',''], comment=comment)
            continue
        
        rec = {
            'code': data['info']['wikia_code'],
            'name': data['info']['sitename'],
            'display': wiki.setdefault('display',''),
            'visible': '',
            'address': data['info']['server'],
            'categories': wiki.setdefault('categories',[]),
            'articles': data['stats']['articles'],
            'images': data['stats']['images'],
            'users': data['stats']['activeusers'],
            'admins': len(admins),
        }
        
        skip = False
        for w in the_list:
            if w['code'] == rec['code']:
                skip = True
                break
        if skip: continue
        
        if type(rec['categories']) != list:
            rec['categories'] = [rec['categories']]
        if rec['display']:
            rec['visible'] = rec['display']
            flag = True
        else:
            rec['visible'] = rec['name']
            flag = False
        
        if (rec['address'][rec['address'].find('://')+3:].find('/')) == -1:
            rec['address'] = rec['address']+'/'
        
        if rec['articles'] != 0:
            the_list.append(rec)
        else:
            comment = '\03{lightred}DELETE\03{default} - no articles'
        
        console_row([rec['visible'],(' ','*')[flag],rec['code'],', '.join(rec['categories']),rec['articles'],rec['images'],rec['users'],rec['admins']], color=(None,'lightred')[rec['users']==0],comment=comment)
    console_end(True)
    
    for wiki in new_wikis:
        code, name, catz = wiki
        
        try:
            data = get_wiki_statinfo(code)
            admins = get_wiki_admins(code, active=True)
        except InvalidWiki, e:
            continue
        
        rec = {
            'code': data['info']['wikia_code'],
            'name': data['info']['sitename'],
            'display': '',
            'visible': data['info']['sitename'],
            'address': data['info']['server'],
            'categories': catz,
            'articles': data['stats']['articles'],
            'images': data['stats']['images'],
            'users': data['stats']['activeusers'],
            'admins': len(admins),
        }
        
        skip = False
        for w in the_list:
            if w['code'] == rec['code']:
                skip = True
                break
        if skip: continue
        
        if type(rec['categories']) != list:
            rec['categories'] = [rec['categories']]
        
        if name != rec['name']:
            rec['visible'] = rec['display'] = name
        
        console_row([rec['visible'],' ',rec['code'],', '.join(rec['categories']),rec['articles'],rec['images'],rec['users'],rec['admins']], color=(None,'lightred')[rec['users']==0])
        the_list.append(rec)
    
    qs(the_list, 'visible')
    wikis = the_list
    
    for rec in the_list:
        for cat in rec['categories']:
            try:
                key = cat.lower()
                if rec['articles'] >= config['limits']['category_article']:
                    cats[key]['articles'] += rec['articles']
                    cats[key]['artcount'] += 1
                if rec['images'] >= config['limits']['category_image']:
                    cats[key]['images'] += rec['images']
                    cats[key]['imgcount'] += 1
            except KeyError: continue
    console_end()
    
    for cat in cats: lens['catname'] = max(lens['catname'], len(cats[cat]['name']))
    console_table(['Name','Avg. articles','Wikis','Avg. images','Wikis'], widths = [lens['catname']])
    for cat in cats:
        if cats[cat]['artcount']: cats[cat]['articles'] = float(float(cats[cat]['articles'])/cats[cat]['artcount'])
        else: cats[cat]['articles'] = 0
        if cats[cat]['imgcount']: cats[cat]['images'] = float(float(cats[cat]['images'])/cats[cat]['imgcount'])
        else: cats[cat]['images'] = 0
        cats[cat]['articles'] = round(cats[cat]['articles'],2)
        cats[cat]['images'] = round(cats[cat]['images'],2)
        
        row = [cats[cat]['name'],cats[cat]['articles'],cats[cat]['artcount'],cats[cat]['images'],cats[cat]['imgcount']]
        console_row(row)
    console_end()
    args['extended'] = args['extended_bak']
    
    render = []
    template = prepare_template('list_record')
    list_count = 0
    inactive_count = 0
    for rec in the_list:
        rec['categories'] = sorted(rec['categories'])
        rec['categories'] = ', '.join(rec['categories'])
        render.append(template % rec)
        list_count += 1
        if rec['users'] == 0:
            inactive_count += 1
    new_list_text = put_between(old_list_text, config['tags']['list'], "\n%s\n" % "\n".join(render))
    
    cats = cats.values()
    qs(cats, 'name')
    
    render = []
    template = prepare_template('category_record')
    cats_count = 0
    for cat in cats:
        render.append(template % cat)
        cats_count += 1
    new_list_text = put_between(new_list_text, config['tags']['categories'], "\n%s\n" % "\n".join(render))
    
    queue_put(page, new_list_text, old_text = old_list_text, comment = __('list_update_summary'))
    save_column(config['pages']['list_column'], list_count, inactive_count)
    save_column(config['pages']['list_cat_column'], cats_count)

def save_column(pagename, count, inactive=0):
    global site
    page = pywikibot.Page(site, pagename)
    old = page.getOldVersion(page.latestRevision())
    
    column = []
    column.append('{| class="{{{class|article-table}}}" style="{{{style|}}}"\n! style="{{{th_style|}}}" | {{{1}}}')
    for x in range(0,count):
        className = ''
        if x >= count-inactive:
            className = ' class="inactive"'
        column.append('|-%s\n| style="{{{td_style|}}}" | %d{{{2|.}}}' % (className, x+1))
    column.append('|}')
    
    column = '%s' % '\n'.join(column)
    new = ''
    try:
        new = put_between(old, ['<onlyinclude>','</onlyinclude>'], column)
    except TagsNotFound:
        pywikibot.output('\n\03{lightyellow}<onlyinclude>\03{default} tags not found. Replacing whole text')
        new = "<onlyinclude>%s</onlyinclude>" % column
    queue_put(page, new, old_text = old, comment = __('column_update_summary') % {'count':count})
def queue_put(page, new_text, old_text = None, comment = None):
    global page_save_queue
    try: page_save_queue
    except NameError: page_save_queue = []
    new_text = new_text.strip()
    
    if old_text != None:
        old_text = old_text.strip()
        if old_text == new_text:
            pywikibot.output('\03{lightaqua}%s\03{default}: No changes necessary' % page.title())
            return
        if pywikibot.simulate:
            pywikibot.output("\n\03{lightgreen}Simulation enabed\03{default} - showing difference instead of saving the page \03{lightaqua}%s\03{default}:" % page.title());
            pywikibot.showDiff(old_text, new_text)
            return
    else:
        if pywikibot.simulate:
            pywikibot.output("\n\03{lightgreen}Simulation enabed\03{default} - page \03{lightaqua}%s\03{default} won't be saved:" % page.title());
            return
    
    if old_text == None:
        more = ' New length: %d' % len(new_text)
    else:
        lenN = len(new_text)
        lenO = len(old_text)
        if lenN > lenO: more = '\03{lightgreen}%d\03{default}' % (lenN - lenO)
        elif lenN < lenO: more = '\03{lightred}%d\03{default}' % (lenN - lenO)
        else: more = '0'
        more = ' \03{default}Length difference: %s' % more
    pywikibot.output("\03{lightgreen}Adding page update to queue \03{lightaqua}%s\03{default}%s" % (page.title(), more));
    
    page_save_queue.append([page, new_text, comment])
    
def run_put_queue():
    global page_save_queue
    try: page_save_queue
    except NameError: page_save_queue = []
        
    pywikibot.output('\n\03{lightyellow}Running save queue with \03{lightaqua}%d\03{lightyellow} %s\03{default}' % (len(page_save_queue), ('elements','element')[len(page_save_queue)==1]))
    for rec in page_save_queue:
        pywikibot.output("\03{lightgreen}Saving page \03{lightaqua}%s\03{default}" % rec[0].title());
        pywikibot.output("\03{lightyellow}Summary:\03{default} %s" % rec[2]);
        
        try: rec[0].put(rec[1], comment = rec[2])
        except pywikibot.EditConflict:
            pywikibot.output("\03{lightred}Edit Conflict:\03{default} skipping");
            continue
    page_save_queue = []
    
def get_all_strikes(text):
    strikes = []
    basic = re.compile("\[\[w:c:(.*?)\|.*?\]\]")
    iter = basic.finditer(text)
    while True:
        try: match = iter.next().group(1)
        except StopIteration: break
        except AttributeError: continue
        else:
            strikes.append(match)
    return strikes
    
def parse_categories(text):
    basic = re.compile("\{\{\s*%s(.*?)\}\}"%re.escape(config['templates']['category_record'][0]), re.S)
    cats = {}
    iter = basic.finditer(text)
    while True:
        try: match = iter.next().group(0)
        except StopIteration: break
        except AttributeError: continue
        else:
            info = template_params(match, 'category_record')
            key = info['name'].lower()
            cats[key] = {
                'name': info['name']
            }
    for cat in cats:
        for x in ['articles','artcount','images','imgcount']:
            cats[cat].setdefault(x,0)
    return cats
    
def allowed_edit(username):
    global config
    user = userlib.User(site,username);
    
    if not user.isRegistered(): return False
    
    groups = user.groups()
    intersect = [i for i in groups if i in config['allowed_groups']]
    
    if len(intersect): return True
    if username in config['allowed_users']: return True
    return False
def template_params(text, template):
    
    global tpl_cache
    try: tpl_cache
    except NameError: tpl_cache = {}
    if template in tpl_cache:
        rx = tpl_cache[template]['rx']
        named = tpl_cache[template]['named']
    else:
        tpl_cache[template] = {}
        tpl_cache[template]['rx'] = rx = prepare_template(template, rx = True)
        tpl_cache[template]['named'] = named = prepare_template(template, rx = True, ret_named = True)
    
    info = {}
    for reg in named:
        m = reg.search(text)
        if m == None: continue
        info.update(m.groupdict())
        
    if rx:
        m = rx.search(text)
        if m != None: info.update(m.groupdict())
    return info
    
def prepare_template(template, rx = False, ret_named = False, ret_unnamed = False):
    global config
    template = config['templates'][template]
    named = []
    unnamed = []
    
    for param in template[1:]:
        if param.find('=') == -1: unnamed.append(param)
        else: named.append(param)
    
    if rx and ret_named:
        for i, nam in enumerate(named):
            m = re.findall(r"%[^\(]*\((.*?)\)", named[i])
            d = {}
            for x in m:
                d[x] = '(?P<%s>[^\|]*?)'%x
            named[i] = nam % d
            named[i] = re.sub(r'^(.*?)\s*=\s*(.*?)\s*$', r'^\s*\|\s*\1\s*\=\s*\2\s*$', named[i])
            named[i] = re.compile(named[i], re.M)
    if ret_named: return named
    if ret_unnamed: return unnamed
    
    if rx and len(unnamed) == 0: return False
    if rx: join = '\s*\|\s*'
    else: join = ' | '
    
    if len(unnamed):
        unnamed = join + join.join(unnamed)
        if not rx: unnamed = unnamed + ' '
    else: unnamed = ''
    
    if rx:
        tpl = "^{{\s*%s%s%s" % (re.escape(template[0]), unnamed, ('\s*$','\s*}}')[len(named)==0])
        m = re.findall(r"%[\(]*\((.*?)\)", tpl)
        d = {}
        for x in m:
            d[x] = '(?P<%s>.*?)'%x
        tpl = tpl % d
        return re.compile(tpl, re.M)
        
    
    if len(named): named = '\n| ' + '\n| '.join(named) + '\n'
    else: named = ''
    
    return "{{%s%s%s}}" % (template[0], unnamed, named)
    
def put_between(text, tag, what):
    start = text.find(tag[0])
    end = text.find(tag[1])
    if start != -1 and end != -1:
        start += len(tag[0])
        text = text[:start] + what + text[end:]
    else:
        raise TagsNotFound(tag, [start != -1,end != -1])
    return text
def get_between(text, tag):
    start = text.find(tag[0])
    end = text.find(tag[1])
    if start != -1 and end != -1:
        start += len(tag[0])
        return text[start:end]
    else:
        raise TagsNotFound(tag, [start != -1,end != -1])
    return text
    
def initialize():
    global force_family, force_lang
    global config, args, new_wikis
        
    new_wikis = []
    args = {}
    args['clean'] = False
    args['forcelist'] = False
    args['forceranking'] = False
    args['listonly'] = False
    args['extended'] = False
    args['saveconfig'] = False
    args['loadconfig'] = False
    args['revisionday'] = None

    for arg in pywikibot.handleArgs():
        if   arg == '-clean':                args['clean'] = True
        elif arg == '-forcelist':            args['forcelist'] = True
        elif arg == '-forceranking':         args['forceranking'] = True
        elif arg == '-listonly':             args['listonly'] = True
        elif arg == '-extended':             args['extended'] = True
        elif arg.startswith('-saveconfig'):  args['saveconfig'] = arg[12:] or 'config.json'
        elif arg.startswith('-loadconfig'):  args['loadconfig'] = arg[12:] or 'config.json'
        elif arg.startswith('-revisionday:'):args['revisionday'] = datetime.datetime.strptime(arg[13:], u'%Y-%m-%d').date()
    
    #log = 'wikia_logs%s/%s.txt' % (('','_sim')[pywikibot.simulate], datetime.datetime.now().isoformat('_').replace(':', '-'))
    #pywikibot.setLogfileStatus(True, log)
    
    args['extended_bak'] = args['extended']
    for arg in sys.argv[1:]:
        if arg.startswith('-family:'): force_family = arg[8:]
        elif arg.startswith('-lang:'): force_lang = arg[6:]
    
    global json_cache
    json_cache = {
        'info': {},
        'stats': {},
        'admins': {},
    }
    global site, current_time
    site = pywikibot.getSite(force_lang, force_family)
    
    current_time = site.family.server_time(force_lang)
    
    pywikibot.output("\03{lightyellow}Working on:\03{default} http://%s/\n" % site.family.langs[force_lang]);
    if args['extended']:
        pywikibot.output("\03{lightyellow}Current server time:\03{default} %s\n\n" % (current_time.isoformat(' ')))
    
    if args['loadconfig']:
        loadchoice = pywikibot.inputChoice("Overwrite config saved on site? Selecting NO will use only missing settings.", ['Yes','No'], ['Y','N'],'Y')
        if loadchoice == 'n': load_config(args['loadconfig'])
    get_config('MediaWiki:Ranking-bot-settings')
    if args['loadconfig'] and loadchoice == 'y': load_config(args['loadconfig'])
    
    check_config()
    
    if args['saveconfig']: dump_config(args['saveconfig'])
    
    if args['loadconfig']:
        choice = pywikibot.inputChoice("Save the setting on the site? Sysop account needed (MediaWiki namespace)", ['Yes','No'], ['Y','N'],'N')
        if choice == 'n': return
        save_config('MediaWiki:Ranking-bot-settings')

class EditRestrict(Exception):
    def __init__(self, value):
        self.val = value
    def __str__(self):
        return self.val
class SkippedRevision(Exception):
    def __init__(self, rev, err = False):
        self.err = err
        self.rev = rev
    def __str__(self):
        if self.err: return 'Revision #%d by %s should be skipped. Reason: %s' % (self.rev[0], self.rev[2], self.err)
        else: return 'Revision #%d by %s should be skipped. User not allowed.' % (self.rev[0], self.rev[2])
class TagsNotFound(Exception):
    def __init__(self, tags, flags):
        self.tags = tags
        self.flags = flags
    def __str__(self):
        if not self.flags[0] and not self.flags[1]:
            return 'Tags not found: "%s" <-> "%s". Couldn\'t find both tags' % (re.escape(self.tags[0]), re.escape(self.tags[1]))
        if not self.flags[0]:
            return 'Tags not found: "%s" <-> "%s". Couldn\'t find starting tag' % (re.escape(self.tags[0]), re.escape(self.tags[1]))
        if not self.flags[1]:
            return 'Tags not found: "%s" <-> "%s". Couldn\'t find ending tag' % (re.escape(self.tags[0]), re.escape(self.tags[1]))
        return 'How the hell did you get here oO'
class InvalidWiki(Exception):
    def __init__(self,url,closed=False):
        self.url = url
        self.closed = closed
    def __str__(self):
        if self.closed:
            return 'Wiki closed: %s' % self.url
        else:
            return 'Wiki not found: %s' % self.url
class JSONError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return self.value

def console_table(names, widths = []):
    global console_settings_cache
    try:console_settings_cache
    except NameError:
        console_settings_cache = {}
    else:
        if len(console_settings_cache):
            console_end()
    console_settings_cache = {}
    console_settings_cache['sep'] = []
    for i, name in enumerate(names):
        try:
            width = max(widths[i], len(name))
        except IndexError:
            width = len(name)
        console_settings_cache[i] = width
        console_settings_cache['sep'].append('-'*(width+2))
    console_settings_cache['sep'] = "+%s+" % '+'.join(console_settings_cache['sep'])
    
    console_end(1)
    console_row(names, 'lightyellow')
    console_end(1)
def console_row(data, color = None, comment = ''):
    global console_settings_cache
    list = []
    for i, cell in enumerate(data):
        try:
            if type(cell) == int:
                content = ('%'+('%d'%console_settings_cache[i])+'d') % cell
                if cell == 0: content = "\03{lightred}%s\03{default}" % content
            elif type(cell) == float:
                content = ('%'+('%d'%console_settings_cache[i])+'.2f') % cell
                if cell == 0: content = "\03{lightred}%s\03{default}" % content
            else:
                content = ('%-'+('%d'%console_settings_cache[i])+'s') % cell
            if color:
                content = "\03{%s}%s\03{default}" % (color,content)
            list.append(content)
        except KeyError: continue
    if comment: comment = ' '+comment
    pywikibot.output('| %s |%s' % (' | '.join(list), comment))
def console_end(flag = False):
    global console_settings_cache
    try:
        pywikibot.output(console_settings_cache['sep'])
        if not flag:
            console_settings_cache = {}
    except KeyError: return
        
def json_from_url(url, tries=5):
    from socket import error as socket_error
    response = ''
    x = 0
    while x<tries:
        try:
            if response: break
            response = urllib2.urlopen(url)
        except urllib2.HTTPError:
            x += 1
        except socket_error:
            x += 1
        except urllib2.URLError, e:
            raise JSONError('URLError: %s' % unicode(e.reason))
            
    if not response: raise JSONError('No response')
    
    response = response.read()
    
    if response == '': raise JSONError('Empty response')
    if response.find('page-Special_CloseWiki') >= 0: raise InvalidWiki(url,True)
    if response.find('page-Community_Central_Not_a_valid_Wikia') >= 0: raise InvalidWiki(url)
    
    try:
        obj = json.loads(response)
    except ValueError:
        raise JSONError('No JSON object could be decoded')
        
    return obj
def get_wiki_admins(address, active=False, useCache=True, useInfoCache=True):
    global json_cache, args, config
    if useCache and address in json_cache['admins']: admins = json_cache['admins'][address]
    else:
        if args['extended']: pywikibot.output('\nJSON: Fetching admins for [%s]' % address)
        url = 'http://%s.wikia.com/api.php?action=query&list=allusers&auprop=editcount&augroup=sysop&format=json' % address
        admins = json_from_url(url)['query']['allusers']
        url = 'http://%s.wikia.com/api.php?action=query&list=allusers&auprop=editcount&augroup=bureaucrat&format=json' % address
        bureaucrats = json_from_url(url)['query']['allusers']
        for user in bureaucrats:
            if user not in admins:
                admins.append(user)
    if not active:
        json_cache['admins'][address] = admins
        return json_cache['admins'][address]
    now = datetime.datetime.strptime(get_wiki_info(address, useCache = useInfoCache)['time'], u'%Y-%m-%dT%H:%M:%SZ')
    activeadmins = []
    for admin in admins:
        if admin['editcount'] == 0: continue
        url = 'http://%s.wikia.com/api.php?action=query&list=usercontribs&uclimit=1&ucuser=%s&ucprop=timestamp&format=json' % (address, urllib2.quote(admin['name'].encode('utf-8')))
        try:
            delta = now-datetime.datetime.strptime(json_from_url(url)['query']['usercontribs'][0]['timestamp'], u'%Y-%m-%dT%H:%M:%SZ')
        except IndexError:
            continue
        if delta.days >= config['admin_active_days']: continue
        activeadmins.append(admin)
    return activeadmins
def get_wiki_info(address, useCache=True):
    global json_cache, args
    if useCache and address in json_cache['info']: return json_cache['info'][address]
    if args['extended']: pywikibot.output('JSON: Fetching info about [%s]' % address)
    url = 'http://%s.wikia.com/api.php?action=query&meta=siteinfo&siprop=general&format=json' % address
    json_cache['info'][address] = json_from_url(url)['query']['general']
    match = re.compile('http:\/\/(www\.)?(.*?)\.wikia\.com', re.I).search(json_cache['info'][address]['server'])
    try: json_cache['info'][address]['wikia_code'] = match.group(2).strip()
    except AttributeError: json_cache['info'][address]['wikia_code'] = address.strip()
    return json_cache['info'][address]
def get_wiki_stats(address, useCache=True):
    global json_cache, args
    if useCache and address in json_cache['stats']: return json_cache['stats'][address]
    if args['extended']: pywikibot.output(u'JSON: Fetching statistics for [%s]' % address)
    url = 'http://%s.wikia.com/api.php?action=query&meta=siteinfo&siprop=statistics&format=json' % address
    json_cache['stats'][address] = json_from_url(url)['query']['statistics']
    return json_cache['stats'][address]
def get_wiki_statinfo(address, useCache=True):
    global json_cache, args
    if useCache and address in json_cache['stats']: stats = json_cache['stats'][address]
    else: stats = None
    if useCache and address in json_cache['info']: info = json_cache['info'][address]
    else: info = None
    if stats == None and info == None:
        if args['extended']: pywikibot.output(u'JSON: Fetching info and statistics for [%s]' % address)
        url = 'http://%s.wikia.com/api.php?action=query&meta=siteinfo&siprop=general|statistics&format=json' % address
        data = json_from_url(url)['query']
        json_cache['stats'][address] = data['statistics']
        json_cache['info'][address] = data['general']
    elif stats == None: stats = get_wiki_stats(address)
    elif info == None: info = get_wiki_info(address)
    
    match = re.compile('http:\/\/(www\.)?(.*?)\.wikia\.com', re.I).search(json_cache['info'][address]['server'])
    try: json_cache['info'][address]['wikia_code'] = match.group(2).strip()
    except AttributeError: json_cache['info'][address]['wikia_code'] = address.strip()
    return {'info':json_cache['info'][address],'stats':json_cache['stats'][address]}
def get_config(page):
    global site, config
    page = pywikibot.Page(site, page)
    pywikibot.output('\03{lightyellow}Processing settings page:\03{default} \03{lightaqua}%s\03{default}' % page.title())
    if not page.exists():
        pywikibot.output("Page doesn't exist")
        return
    page.permalink()
    text = page.getOldVersion(page.latestRevision())
    text = pywikibot.replaceExcept(text, '< */? *(pre|source).*?>','',[])
    
    decoded = json.loads(text);
    
    tree_update(config,decoded)
def print_config(config, name, indent = ''):
    typ = type(config).__name__
    name = '\03{lightyellow}%s\03{default}: ' % name
    value = ''
    if typ == 'bool': value = '\03{lightaqua}%s\03{default}' % config
    elif typ == 'str' or typ == 'unicode':
        if len(config) > 75: config = config[:75]+' \03{lightaqua}...\03{default}'
        value = '"\03{default}%s"' % config.replace('\n', '\\n')
    elif typ == 'int': value = '\03{lightaqua}%d\03{default}' % config
    elif typ == 'float': value = '\03{lightaqua}%.3f\03{default}' % config
    elif typ == 'NoneType': value = '\03{lightred}----- MISSING -----\03{default}'
    pywikibot.output('%s%s %s' % (indent, name, value))
    if typ == 'dict':
        for key in config:
            print_config(config[key], key, '    '+indent)
    elif typ == 'list':
        i = 0
        for elem in config:
            print_config(elem, '%d'%i, '    '+indent);
            i = i+1
def load_config(file):
    global config
    pywikibot.output('\n\03{lightyellow}Reading config JSON from\03{default}: %s' % file)
    f = codecs.open(file, "r", "utf-8")
    obj = json.load(f, "utf-8")
    tree_update(config, obj)
def dump_config(file):
    global config
    dup = config.copy()
    pywikibot.output('\n\03{lightyellow}Dumping config as JSON object to\03{default}: %s' % file)
    f = codecs.open(file, "w", "utf-8")
    json.dump(dup, f, indent=2, sort_keys=True)
def save_config(page):
    global site, config, msg, force_lang
    page = pywikibot.Page(site, page)
    pywikibot.output('\03{lightyellow}Saving settings on page:\03{default} \03{lightaqua}%s\03{default}' % page.title())
    if not page.exists():
        choice = pywikibot.inputChoice("Page doesn't exist. Create?", ['Yes','No'], ['Y','N'],'N')
        pywikibot.output(choice)
        if choice != 'y': return
        create = True
    else:
        old = page.getOldVersion(page.latestRevision())
        create = False
    
    dup = config.copy()
    new = '<sou'+'rce lang="javascript">\n%s\n</sou'+'rce>' % json.dumps(dup, indent=2, sort_keys=True)
    if not create and old == new:
        pywikibot.output('No changes necessary')
    else:
        queue_put(page, new, old_text = old, comment = __('setting_update_summary'))
def check_tree(obj, miss = 0):
    if obj == None: return 1
    if isinstance(obj, dict):
        miss = 0
        for x in obj:
            miss += check_tree(obj[x])
        return miss
    return 0
def check_config():
    global config, args
    
    missing = check_tree(config)
    
    if missing:
        pywikibot.output('\n\03{lightyellow}Current config\03{default}:')
        for key in config:
            print_config(config[key], key, ' - ')
    
    if missing:
        pywikibot.output('\n\n\03{lightred}FATAL ERROR:\03{default} %s - use the log above in order to pinpoint the problem' % (('There are \03{lightaqua}%d\03{default} missing settings','There is \03{lightaqua}%d\03{default} missing setting')[missing == 1] % missing))
        pywikibot.stopme()
        return exit('NoConfig')

def tree_update(tree, other):
    for key in other:
        if isinstance(other[key], dict): tree_update(tree[key], other[key])
        else: tree[key] = other[key]
def var_dump(v):
    try:
        dump = json.dumps(v,indent=2, sort_keys=True)
    except TypeError:
        dump = "%s" % v
    pywikibot.output("VAR DUMP (%s):\n%s\n=========" % (type(v), dump))

# Quick sort
def qs(l, x):
    qsr (l, 0, len (l) - 1, x)
    return l
def qsr(l , s, e, x):
    if e > s :
        p = qsp (l, s, e, x)
        qsr (l, s, p - 1, x)
        qsr (l, p + 1, e, x)
def qsp( l, s, e, x):
    a = ( s + e ) / 2
    if x is not None:
        if l[s][x] > l[a][x] :
            l[s], l [a] = l [a], l[s]
        if l[s][x] > l [e][x] :
            l[s], l[e] = l[e], l[s]
        if l[a][x] > l[e][x] :
            l[a], l[e] = l[e], l[a]   
        l [a], l [s] = l[s], l[a]
    else:
        if l[s] > l[a] :
            l[s], l [a] = l [a], l[s]
        if l[s] > l [e] :
            l[s], l[e] = l[e], l[s]
        if l[a] > l[e] :
            l[a], l[e] = l[e], l[a]   
        l [a], l [s] = l[s], l[a]

    p = s
    i = s + 1
    j = e
    
    if x is not None:
        while ( True ):
            while ( i <= e and l[i][x] <= l[p][x] ):
                i += 1
            while ( j >= s and l[j][x] > l[p][x] ):
                j -= 1
            if i >= j :
                break
            else:
                l[i], l[j] = l[j], l[i]  
    else:
        while ( True ):
            while ( i <= e and l[i] <= l[p] ):
                i += 1
            while ( j >= s and l[j] > l[p] ):
                j -= 1
            if i >= j :
                break
            else:
                l[i], l[j] = l[j], l[i]  
    
    l[j], l[p] = l[p], l[j]
    return j

def __(key, code = None):
    global force_lang, msg, config
    if key in config['msg']: return config['msg'][key]
    if code == None: code = force_lang
    if code not in msg: return msg['en'][key]
    return msg[code][key]
msg = {
    'en': {
        'setting_update_summary': u"Robot: Updating settings",
        'talk_update_summary': u"Robot: Updating queue",
        'list_update_summary': u"Robot: Updating wiki list",
        'ranking_update_summary': u"Robot: Updating wiki ranking",
        'column_update_summary': u"Robot: Updating static column. Row count: %(count)d",
        
        'wrong_language': u"Only wikis in one of the listed languages (%(languages)s) - given: %(lang)s",
        'no_wiki': u"wiki doesn't exist",
        'on_the_list': u"already on the list",
    },
    'pl': {
        'setting_update_summary': u"Robot aktualizuje ustawienia",
        'talk_update_summary': u"Robot aktualizuje listę wiki oczekujących na dodanie",
        'list_update_summary': u"Robot aktualizuje listę wiki",
        'ranking_update_summary': u"Robot aktualizuje ranking wiki",
        'column_update_summary': u"Robot aktualizuje statyczną kolumnę. Liczba wierszy %(count)d",
        
        'wrong_language': u"Tylko wiki w jednym z podanych jęzków (%(languages)s) - język wiki: %(lang)s",
        'no_wiki': u"wiki nie istnieje",
        'on_the_list': u"już jest na liście",
    }
}

if __name__ == "__main__":
    main()
    pywikibot.stopme()
    sys.exit(0)