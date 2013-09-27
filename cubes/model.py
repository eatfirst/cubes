# -*- coding=utf -*-
"""Logical model."""

import copy

from collections import OrderedDict

from .common import IgnoringDictionary, get_logger, to_label
from .errors import *

__all__ = [
    "Model",
    "Cube",
    "Dimension",
    "Hierarchy",
    "Level",
    "AttributeBase",
    "Attribute",
    "Measure",
    "MeasureAggregate",

    "create_attribute",
    "create_measure",
    "create_measure_aggregate",
    "attribute_list",

    # FIXME: depreciated. affected: formatter.py
    "split_aggregate_ref",
    "aggregate_ref",

]


def assert_instance(obj, class_, label):
    """Raises ArgumentError when `obj` is not instance of `cls`"""
    if not isinstance(obj, class_):
        raise ModelInconsistencyError("%s should be sublcass of %s, "
                                      "provided: %s" % (label,
                                                        class_.__name__,
                                                        type(obj).__name__))


def assert_all_instances(list_, class_, label):
    """Raises ArgumentError when objects in `list_` are not instances of
    `cls`"""
    for obj in list_:
        assert_instance(obj, class_, label)


class Model(object):
    def __init__(self, name=None, cubes=None, dimensions=None, locale=None,
                 label=None, description=None, info=None, mappings=None,
                 provider=None, metadata=None, translations=None):
        """
        Logical representation of data. Base container for cubes and
        dimensions.

        Attributes:

        * `name` - model name
        * `cubes` -  list of `Cube` instances
        * `dimensions` - list of `Dimension` instances
        * `locale` - locale code of the model
        * `label` - human readable name - can be used in an application
        * `description` - longer human-readable description of the model
        * `info` - custom information dictionary

        * `metadata` – a dictionary describing the model
        * `provider` – an object that creates model objects

        """
        # * `mappings` – model-wide mappings of logical-to-physical attributes

        # Basic information
        self.name = name
        self.label = label
        self.description = description
        self.locale = locale
        self.info = info or {}
        self.provider = provider
        self.metadata = metadata

        # Physical information
        self.mappings = mappings

        self._dimensions = OrderedDict()
        if dimensions:
            for dim in dimensions:
                self.add_dimension(dim)

        self.cubes = OrderedDict()
        if cubes:
            for cube in cubes:
                self.add_cube(cube)

        self.translations = translations or {}

    def __str__(self):
        return 'Model(%s)' % self.name

    def add_cube(self, cube):
        """Adds cube to the model and also assigns the model to the cube. If
        cube has a model assigned and it is not this model, then error is
        raised.

        Raises `ModelInconsistencyError` when trying to assing a cube that is
        already assigned to a different model or if trying to add a dimension
        with existing name but different specification.
        """

        assert_instance(cube, Cube, "cube")

        # Collect dimensions from cube
        my_dimensions = set(self.dimensions)
        my_dimension_names = set([dim.name for dim in self.dimensions])

        for dimension in cube.dimensions:
            if dimension not in my_dimensions:
                if dimension.name not in my_dimension_names:
                    self.add_dimension(dimension)
                else:
                    raise ModelError("Dimension %s of cube %s has different "
                                     "specification as model's dimension"
                                     % (dimension.name, cube.name))

        self.cubes[cube.name] = cube

    def remove_cube(self, cube):
        """Removes cube from the model"""
        del self.cubes[cube.name]

    def cube(self, cube):
        """Get a cube with name `name` or coalesce object to a cube."""
        try:
            if isinstance(cube, basestring):
                cube = self.cubes[cube]
        except KeyError as e:
            raise ModelError("No such cube '%s'" % str(e))
        return cube

    def add_dimension(self, dimension):
        """Add dimension to model. Replace dimension with same name"""
        assert_instance(dimension, Dimension, "dimension")

        if dimension.name in self._dimensions:
            raise ModelInconsistencyError("Dimension '%s' already exists "
                                          "in model '%s'" %
                                          (dimension.name, self.name))

        self._dimensions[dimension.name] = dimension

    def remove_dimension(self, dimension):
        """Remove a dimension from receiver"""
        del self._dimensions[dimension.name]

    @property
    def dimensions(self):
        return self._dimensions.values()

    def dimension(self, dim):
        """Get dimension by name or by object. Raises `NoSuchDimensionError`
        when there is no dimension `dim`."""

        if isinstance(dim, basestring):
            if dim in self._dimensions:
                return self._dimensions[dim]
            else:
                raise NoSuchDimensionError("Unknown dimension with name '%s' "
                                           "in model '%s'" % (dim, self.name))
        elif dim.name in self._dimensions:
            return dim
        else:
            raise NoSuchDimensionError("Unknown dimension '%s' in "
                                       "model '%s'" % (dim, self.name))

    def to_dict(self, **options):
        """Return dictionary representation of the model. All object
        references within the dictionary are name based

        * `full_attribute_names` - if set to True then attribute names will be
          written as ``dimension_name.attribute_name``
        """

        out = IgnoringDictionary()

        out["name"] = self.name
        out["label"] = self.label
        out["description"] = self.description
        out["info"] = self.info

        dims = [dim.to_dict(**options) for dim in self._dimensions.values()]
        out["dimensions"] = dims

        cubes = [cube.to_dict(**options) for cube in self.cubes.values()]
        out["cubes"] = cubes

        if options.get("with_mappings"):
            out["mappings"] = self.mappings

        return out

    def __eq__(self, other):
        if other is None or type(other) != type(self):
            return False
        if self.name != other.name or self.label != other.label \
                or self.description != other.description:
            return False
        elif self.dimensions != other.dimensions:
            return False
        elif self.cubes != other.cubes:
            return False
        elif self.info != other.info:
            return False
        return True

    def validate(self):
        """Validate the model, check for model consistency. Validation result
        is array of tuples in form: (validation_result, message) where
        validation_result can be 'warning' or 'error'.

        Returs: array of tuples
        """

        results = []

        ################################################################
        # 1. Chceck dimensions
        is_fatal = False
        for dim_name, dim in self._dimensions.items():
            if not issubclass(dim.__class__, Dimension):
                results.append(('error', "Dimension '%s' is not a subclass "
                                "of Dimension class" % dim_name))
                is_fatal = True

        # We are not going to continue if there are no valid dimension objects,
        # as more errors migh emerge
        if is_fatal:
            return results

        for dim in self.dimensions:
            results.extend(dim.validate())

        ################################################################
        # 2. Chceck cubes

        if not self.cubes:
            results.append(('warning', 'No cubes defined'))
        else:
            for cube_name, cube in self.cubes.items():
                results.extend(cube.validate())

        return results

    def is_valid(self, strict=False):
        """Check whether model is valid. Model is considered valid if there
        are no validation errors. If you want to be sure that there are no
        warnings as well, set *strict* to ``True``. If `strict` is ``False``
        only errors are considered fatal, if ``True`` also warnings will make
        model invalid.

        Returns ``True`` when model is valid, otherwise returns ``False``.
        """
        results = self.validate()
        if not results:
            return True

        if strict:
            return False

        for result in results:
            if result[0] == 'error':
                return False

        return True

    def _add_translation(self, lang, translation):
        self.translations[lang] = translation

    def localize(self, translation):
        """Return localized version of the model.

        `translation` might be a string or a dicitonary. If it is a string,
        then it represents locale name from model's localizations provided on
        model creation. If it is a dictionary, it should contains full model
        translation that is going to be applied.


        Translation dictionary structure example::

            {
                "locale": "sk",
                "cubes": {
                    "sales": {
                        "label": "Predaje",
                        "measures":
                            {
                                "amount": "suma",
                                "discount": {"label": "zľava",
                                             "description": "uplatnená zľava"}
                            }
                    }
                },
                "dimensions": {
                    "date": {
                        "label": "Dátum"
                        "attributes": {
                            "year": "rok",
                            "month": {"label": "mesiac"}
                        },
                        "levels": {
                            "month": {"label": "mesiac"}
                        }
                    }
                }
            }

        .. note::

            Whenever master model changes, you should call this method to get
            actualized localization of the original model.
        """

        model = copy.deepcopy(self)

        if type(translation) == str or type(translation) == unicode:
            try:
                translation = self.translations[translation]
            except KeyError:
                raise ModelError("Model has no translation for %s" %
                                 translation)

        if "locale" not in translation:
            raise ValueError("No locale specified in model translation")

        model.locale = translation["locale"]
        localize_common(model, translation)

        if "cubes" in translation:
            for name, cube_trans in translation["cubes"].items():
                cube = model.cube(name)
                cube.localize(cube_trans)

        if "dimensions" in translation:
            dimensions = translation["dimensions"]
            for name, dim_trans in dimensions.items():
                # Use translation template if exists, similar to dimension
                # template
                template_name = dim_trans.get("template")

                if False and template_name:
                    try:
                        template = dimensions[template_name]
                    except KeyError:
                        raise ModelError("No translation template '%s' for "
                                "dimension '%s'" % (template_name, name))

                    template = dict(template)
                    template.update(dim_trans)
                    dim_trans = template

                dim = model.dimension(name)
                dim.localize(dim_trans)

        return model

    def localizable_dictionary(self):
        """Get model locale dictionary - localizable parts of the model"""
        locale = {}
        locale.update(get_localizable_attributes(self))
        clocales = {}
        locale["cubes"] = clocales
        for cube in self.cubes.values():
            clocales[cube.name] = cube.localizable_dictionary()

        dlocales = {}
        locale["dimensions"] = dlocales
        for dim in self.dimensions:
            dlocales[dim.name] = dim.localizable_dictionary()

        return locale


class ModelObject(object):
    """Base classs for all model objects."""

    def __init__(self, name=None, label=None, description=None, info=None):
        self.name = name
        self.label = label
        self.description = description
        self.info = info


class Cube(object):
    def __init__(self, name, dimensions=None, measures=None, aggregates=None,
                 label=None, details=None, mappings=None, joins=None,
                 fact=None, key=None, description=None, browser_options=None,
                 info=None, linked_dimensions=None,
                 locale=None, category=None, datastore=None, **options):

        """Create a new Cube model object.

        Properties:

        * `name`: cube name, used as identifier
        * `measures`: list of measures – numerical attributes
        * `aggregates`: list of measure aggregates – measures with applied
          aggregation functions or natively aggregated values
        * `label`: human readable cube label
        * `details`: list of detail attributes
        * `description` - human readable description of the cube
        * `key`: fact key field (if not specified, then backend default key
          will be used, mostly ``id`` for SLQ or ``_id`` for document based
          databases)
        * `info` - custom information dictionary, might be used to store
          application/front-end specific information
        * `locale`: cube's locale

        There are two ways how to assign dimensions to the cube: specify them
        during cube initialization in `dimensions` by providing a list of
        `Dimension` objects. Alternatively you can set `linked_dimensions`
        list with dimension names and the link the dimension using
        :meth:`Cube.add_dimension()`.

        Physical properties of the cube are described in the following
        attributes. They are used by the backends:

        * `mappings` - backend-specific logical to physical mapping
          dictionary. Keys and values of this dictionary are interpreted by
          the backend.
        * `joins` - backend-specific join specification (used for example in
          the SQL backend). It should be a list of dictionaries.
        * `fact` - fact table (collection, dataset, ...) name
        * `datastore` - name of datastore where the cube belongs
        * `browser_options` - dictionary of other options used by the backend
          - refer to the backend documentation to see what options are used
            (for example SQL browser might look here for ``denormalized_view``
            in case of denormalized browsing)
        """

        self.name = name
        self.locale = locale

        # User-oriented metadata
        self.label = label
        self.description = description
        self.info = info or {}
        # backward compatibility
        self.category = category or self.info.get("category")

        # Physical properties
        self.mappings = mappings
        self.fact = fact
        self.joins = joins
        self.key = key
        self.browser_options = browser_options or {}
        self.datastore = datastore or options.get("datastore")
        self.browser = options.get("browser")

        self.linked_dimensions = linked_dimensions or []
        self._dimensions = OrderedDict()

        if dimensions:
            if all([isinstance(dim, Dimension) for dim in dimensions]):
                for dim in dimensions:
                    self.add_dimension(dim)
            else:
                raise ModelError("Dimensions for cube initialization should be "
                                 "a list of Dimension instances.")
        #
        # Prepare measures and aggregates
        #
        self.measures = attribute_list(measures, Measure)

        # Set aggregates:
        # IF aggregate list is provided, then use the list
        # IF no aggregate list is provided, then derive default aggregates
        # from the measures

        if aggregates is not None:
            # Get explicit aggregates
            aggregates = attribute_list(aggregates, MeasureAggregate)

            # Check existence of measures
            for aggregate in aggregates:
                if aggregate.measure \
                        and aggregate.measure not in self._measures:
                    raise NoSuchAttributeError("No measure %s for aggregate"
                                                "%s" % (aggregate.measure,
                                                        str(aggregate)))
        else:
            # Create default aggregates from the list of measures
            aggregates = []
            for measure in self.measures:
                aggregates += measure.default_aggregates()

        self.aggregates = aggregates

        self.details = attribute_list(details, Attribute)

    @property
    def measures(self):
        return self._measures.values()

    @measures.setter
    def measures(self, measures):
        self._measures = OrderedDict((m.name, m) for m in measures)

    @property
    def aggregates(self):
        return self._aggregates.values()

    @aggregates.setter
    def aggregates(self, aggregates):
        self._aggregates = OrderedDict((m.name, m) for m in aggregates)

    def aggregates_for_measure(self, name):
        """Returns aggregtates for measure with `name`. Only direct function
        aggregates are returned. If the measure is specified in an expression,
        the aggregate is not included in the returned list"""

        return [agg for agg in self.aggregates if agg.name == name]

    def get_aggregates(self, names):
        """Get a list of aggregates with `names`"""
        return [self._aggregates[name] for name in names]

    def add_dimension(self, dimension):
        """Add dimension to cube. Replace dimension with same name. Raises
        `ModelInconsistencyError` when dimension with same name already exists
        in the receiver. """

        if not isinstance(dimension, Dimension):
            raise ArgumentError("Dimension added to cube '%s' is not a "
                                "Dimension instance." % self.name)

        if dimension.name in self._dimensions:
            raise ModelError("Dimension with name %s already exits "
                             "in cube %s" % (dimension.name, self.name))


        self._dimensions[dimension.name] = dimension

    def remove_dimension(self, dimension):
        """Remove a dimension from receiver. `dimension` can be either
        dimension name or dimension object."""

        dim = self.dimension(dimension)
        del self._dimensions[dim.name]

    @property
    def dimensions(self):
        return self._dimensions.values()

    def dimension(self, obj):
        """Get dimension object. If `obj` is a string, then dimension with
        given name is returned, otherwise dimension object is returned if it
        belongs to the cube.

        Raises `NoSuchDimensionError` when there is no such dimension.
        """

        # FIXME: raise better exception if dimension does not exist, but is in
        # the list of required dimensions

        if not obj:
            raise NoSuchDimensionError("Requested dimension should not be none (cube '%s')" % \
                                self.name)

        if isinstance(obj, basestring):
            if obj in self._dimensions:
                return self._dimensions[obj]
            else:
                raise NoSuchDimensionError("cube '%s' has no dimension '%s'" %
                                    (self.name, obj))
        elif isinstance(obj, Dimension):
             return obj
        else:
            raise NoSuchDimensionError("Invalid dimension or dimension "
                                       "reference '%s' for cube '%s'" %
                                            (obj, self.name))

    def measure(self, name):
        """Get measure object. If `obj` is a string, then measure with given
        name is returned, otherwise measure object is returned if it belongs
        to the cube. Returned object is of `Attribute` type.

        Raises `NoSuchAttributeError` when there is no such measure or when
        there are multiple measures with the same name (which also means that
        the model is not valid).
        """

        name = str(name)
        try:
            return self._measures[name]
        except KeyError:
            raise NoSuchAttributeError("cube '%s' has no measure '%s'" %
                                            (self.name, name))

    def measure_aggregate(self, name):
        """Returns a measure aggregate by name."""
        name = str(name)
        try:
            return self._measures[name]
        except KeyError:
            raise NoSuchAttributeError("cube '%s' has no measure aggregate "
                                            "'%s'" % (self.name, name))


    def get_measures(self, measures):
        """Get a list of measures as `Attribute` objects. If `measures` is
        `None` then all cube's measures are returned."""

        array = []

        for measure in measures or self.measures:
            array.append(self.measure(measure))

        return array

    def to_dict(self, expand_dimensions=False, with_mappings=True, **options):
        """Convert to a dictionary. If `with_mappings` is ``True`` (which is
        default) then `joins`, `mappings`, `fact` and `options` are included.
        Should be set to ``False`` when returning a dictionary that will be
        provided in an user interface or through server API.
        """

        out = IgnoringDictionary()
        out["name"] = self.name
        out["info"] = self.info
        out["category"] = self.category

        if options.get("create_label"):
            out["label"] = self.label or to_label(self.name)
        else:
            out["label"] = self.label

        measures = [m.to_dict(**options) for m in self.measures]
        out["measures"] = measures

        aggregates = [m.to_dict(**options) for m in self.aggregates]
        out["aggregates"] = aggregates

        details = [a.to_dict(**options) for a in self.details]
        out["details"] = details

        if expand_dimensions:
            dims = [dim.to_dict() for dim in self.dimensions]
        else:
            dims = [dim.name for dim in self.dimensions]

        out["dimensions"] = dims

        if with_mappings:
            out["mappings"] = self.mappings
            out["fact"] = self.fact
            out["joins"] = self.joins
            out["browser_options"] = self.browser_options

        out["key"] = self.key
        return out

    def __eq__(self, other):
        if other is None or type(other) != type(self):
            return False
        if self.name != other.name or self.label != other.label \
            or self.description != other.description:
            return False
        elif self.dimensions != other.dimensions \
                or self.measures != other.measures \
                or self.aggregates != other.aggregates \
                or self.details != other.details \
                or self.mappings != other.mappings \
                or self.joins != other.joins \
                or self.browser_options != other.browser_options \
                or self.info != other.info:
            return False
        return True

    def validate(self):
        """Validate cube. See Model.validate() for more information. """
        results = []

        # Check whether all attributes, measures and keys are Attribute objects
        # This is internal consistency chceck

        measures = set()

        for measure in self.measures:
            if not isinstance(measure, Attribute):
                results.append(('error',
                                 "Measure '%s' in cube '%s' is not instance"
                                 "of Attribute" % (measure, self.name)))
            else:
                measures.add(str(measure))

        details = set()
        for detail in self.details:
            if not isinstance(detail, Attribute):
                results.append( ('error', "Detail '%s' in cube '%s' is not instance of Attribute" % (detail, self.name)) )
            if str(detail) in details:
                results.append( ('error', "Duplicate detail '%s' in cube '%s'"\
                                            % (detail, self.name)) )
            elif str(detail) in measures:
                results.append( ('error', "Duplicate detail '%s' in cube '%s'"
                                          " - specified also as measure" \
                                            % (detail, self.name)) )
            else:
                details.add(str(detail))

        # 2. check whether dimension attributes are unique

        return results

    def localize(self, locale):
        # FIXME: this needs revision/testing – it might be broken
        localize_common(self,locale)

        attr_locales = locale.get("measures")
        if attr_locales:
            for attrib in self.measures:
                if attrib.name in attr_locales:
                    localize_common(attrib, attr_locales[attrib.name])

        attr_locales = locale.get("aggregates")
        if attr_locales:
            for attrib in self.aggregates:
                if attrib.name in attr_locales:
                    localize_common(attrib, attr_locales[attrib.name])

        attr_locales = locale.get("details")
        if attr_locales:
            for attrib in self.details:
                if attrib.name in attr_locales:
                    localize_common(attrib, attr_locales[attrib.name])

    def localizable_dictionary(self):
        # FIXME: this needs revision/testing – it might be broken
        locale = {}
        locale.update(get_localizable_attributes(self))

        mdict = {}
        locale["measures"] = mdict

        for measure in self.measures:
            mdict[measure.name] = measure.localizable_dictionary()

        mdict = {}
        locale["details"] = mdict

        for measure in self.details:
            mdict[measure.name] = measure.localizable_dictionary()

        return locale

    def __str__(self):
        return self.name


class Dimension(object):
    """
    Cube dimension.

    """
    def __init__(self, name, levels, hierarchies=None,
                 default_hierarchy_name=None, label=None, description=None,
                 info=None, **desc):

        """Create a new dimension

        Attributes:

        * `name`: dimension name
        * `levels`: list of dimension levels (see: :class:`cubes.Level`)
        * `hierarchies`: list of dimension hierarchies. If no hierarchies are
          specified, then default one is created from ordered list of `levels`.
        * `default_hierarchy_name`: name of a hierarchy that will be used when
          no hierarchy is explicitly specified
        * `label`: dimension name that will be displayed (human readable)
        * `description`: human readable dimension description
        * `info` - custom information dictionary, might be used to store
          application/front-end specific information (icon, color, ...)

        Dimension class is not meant to be mutable. All level attributes will
        have new dimension assigned.

        Note that the dimension will claim ownership of levels and their
        attributes. You should make sure that you pass a copy of levels if you
        are cloning another dimension.
        """

        self.name = name

        self.label = label
        self.description = description
        self.info = info or {}

        if not levels:
            raise ModelError("No levels specified for dimension %s"
                             % self.name)

        self._set_levels(levels)

        if hierarchies:
            self.hierarchies = dict((hier.name, hier) for hier in hierarchies)
        else:
            hier = Hierarchy("default", self.levels)
            self.hierarchies = {"default": hier}

        # Claim ownership of hierarchies
        for hier in self.hierarchies.values():
            hier.dimension = self

        self._flat_hierarchy = None
        self.default_hierarchy_name = default_hierarchy_name

        # FIXME: is this needed anymore?
        self.key_field = desc.get("key_field")

    def _set_levels(self, levels):
        """Set dimension levels. `levels` should be a list of `Level`
        instances."""

        self._levels = OrderedDict()
        self._attributes = OrderedDict()

        try:
            for level in levels:
                self._levels[level.name] = level
        except AttributeError:
            raise ModelInconsistencyError("Levels in dimension %s do not look "
                                          "like Level instances" % self.name)

        # Collect attributes
        self._attributes = OrderedDict()
        for level in self.levels:
            self._attributes.update([(a.name, a) for a in level.attributes])

        for attr in self._attributes.values():
            attr.dimension = self

    def __eq__(self, other):
        if other is None or type(other) != type(self):
            return False
        if self.name != other.name or self.label != other.label \
            or self.description != other.description:
            return False
        elif self._default_hierarchy() != other._default_hierarchy():
            return False

        if self._levels != other._levels:
            return False

        if other.hierarchies != self.hierarchies:
            return False

        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    @property
    def has_details(self):
        """Returns ``True`` when each level has only one attribute, usually
        key."""

        return any([level.has_details for level in self._levels.values()])

    @property
    def levels(self):
        """Get list of all dimension levels. Order is not guaranteed, use a
        hierarchy to have known order."""
        return self._levels.values()

    @property
    def level_names(self):
        """Get list of level names. Order is not guaranteed, use a hierarchy
        to have known order."""
        return self._levels.keys()

    def level(self, obj):
        """Get level by name or as Level object. This method is used for
        coalescing value"""
        if isinstance(obj, basestring):
            if obj not in self._levels:
                raise KeyError("No level %s in dimension %s" %
                               (obj, self.name))
            return self._levels[obj]
        elif isinstance(obj, Level):
            return obj
        else:
            raise ValueError("Unknown level object %s (should be a string "
                             "or Level)" % obj)

    def hierarchy(self, obj=None):
        """Get hierarchy object either by name or as `Hierarchy`. If `obj` is
        ``None`` then default hierarchy is returned."""

        if obj is None:
            return self._default_hierarchy()
        if isinstance(obj, basestring):
            if obj not in self.hierarchies:
                raise ModelError("No hierarchy %s in dimension %s" %
                                 (obj, self.name))
            return self.hierarchies[obj]
        elif isinstance(obj, Hierarchy):
            return obj
        else:
            raise ValueError("Unknown hierarchy object %s (should be a "
                             "string or Hierarchy instance)" % obj)

    def attribute(self, reference):
        """Get dimension attribute from `reference`."""
        return self._attributes[str(reference)]

    @property
    def default_hierarchy(self):
        """Get default hierarchy specified by ``default_hierarchy_name``, if
        the variable is not set then get a hierarchy with name *default*

        .. warning::

            Depreciated. Use `Dimension.hierarchy()` instead.

        """
        logger = get_logger()
        logger.warn("Dimension.default_hierarchy is depreciated, use "
                    "hierarchy() instead")
        return self._default_hierarchy()

    def _default_hierarchy(self):
        """Get default hierarchy specified by ``default_hierarchy_name``, if
        the variable is not set then get a hierarchy with name *default*"""

        if self.default_hierarchy_name:
            hierarchy_name = self.default_hierarchy_name
        else:
            hierarchy_name = "default"

        hierarchy = self.hierarchies.get(hierarchy_name)

        if not hierarchy:
            if len(self.hierarchies) == 1:
                hierarchy = self.hierarchies.values()[0]
            elif not self.hierarchies:
                if len(self.levels) == 1:
                    if not self._flat_hierarchy:
                        self._flat_hierarchy = Hierarchy(name=level.name,
                                                         dimension=self,
                                                         levels=[levels[0]])

                    return self._flat_hierarchy
                elif len(self.levels) > 1:
                    raise ModelError("There are no hierarchies in dimenson %s "
                                     "and there are more than one level" %
                                     self.name)
                else:
                    raise ModelError("There are no hierarchies in dimenson "
                                     "%s and there are no levels to make "
                                     "hierarchy from" % self.name)
            else:
                raise ModelError("No default hierarchy specified in dimension"
                                 " '%s' and there is more (%d) than one "
                                 "hierarchy defined" %
                                 (self.name, len(self.hierarchies)))

        return hierarchy

    @property
    def is_flat(self):
        """Is true if dimension has only one level"""
        return len(self.levels) == 1

    def key_attributes(self):
        """Return all dimension key attributes, regardless of hierarchy. Order
        is not guaranteed, use a hierarchy to have known order."""

        return [level.key for level in self._levels.values()]

    def all_attributes(self):
        """Return all dimension attributes regardless of hierarchy. Order is
        not guaranteed, use :meth:`cubes.Hierarchy.all_attributes` to get
        known order. Order of attributes within level is preserved."""

        return list(self._attributes.values())

    def to_dict(self, **options):
        """Return dictionary representation of the dimension"""

        out = IgnoringDictionary()
        out["name"] = self.name
        out["info"] = self.info
        out["default_hierarchy_name"] = self.default_hierarchy_name

        if options.get("create_label"):
            out["label"] = self.label or to_label(self.name)
        else:
            out["label"] = self.label

        out["levels"] = [level.to_dict(**options) for level in self.levels]
        out["hierarchies"] = [hier.to_dict(**options) for hier in
                                                    self.hierarchies.values()]

        # Use only for reading, during initialization these keys are ignored,
        # as they are derived
        # They are provided here for convenience.
        out["is_flat"] = self.is_flat
        out["has_details"] = self.has_details

        return out

    def validate(self):
        """Validate dimension. See Model.validate() for more information. """
        results = []

        if not self.levels:
            results.append(('error', "No levels in dimension '%s'"
                            % (self.name)))
            return results

        if not self.hierarchies:
            msg = "No hierarchies in dimension '%s'" % (self.name)
            if self.is_flat:
                level = self.levels[0]
                results.append(('default',
                                msg + ", flat level '%s' will be used" %
                                      (level.name)))
            elif len(self.levels) > 1:
                results.append(('error',
                                msg + ", more than one levels exist (%d)" %
                                      len(self.levels)))
            else:
                results.append(('error', msg))
        else:  # if self.hierarchies
            if not self.default_hierarchy_name:
                if len(self.hierarchies) > 1 and \
                        not "default" in self.hierarchies:
                    results.append(('error',
                                    "No defaut hierarchy specified, there is "
                                    "more than one hierarchy in dimension "
                                    "'%s'" % self.name))

        if self.default_hierarchy_name \
                and not self.hierarchies.get(self.default_hierarchy_name):
            results.append(('error',
                            "Default hierarchy '%s' does not exist in "
                            "dimension '%s'" %
                            (self.default_hierarchy_name, self.name)))

        attributes = set()
        first_occurence = {}

        for level_name, level in self._levels.items():
            if not level.attributes:
                results.append(('error',
                                "Level '%s' in dimension '%s' has no "
                                "attributes" % (level.name, self.name)))
                continue

            if not level.key:
                attr = level.attributes[0]
                results.append(('default',
                                "Level '%s' in dimension '%s' has no key "
                                "attribute specified, first attribute will "
                                "be used: '%s'"
                                % (level.name, self.name, attr)))

            if level.attributes and level.key:
                if level.key.name not in [a.name for a in level.attributes]:
                    results.append(('error',
                                    "Key '%s' in level '%s' in dimension "
                                    "'%s' is not in level's attribute list"
                                    % (level.key, level.name, self.name)))

            for attribute in level.attributes:
                attr_name = attribute.ref()
                if attr_name in attributes:
                    first = first_occurence[attr_name]
                    results.append(('error',
                                    "Duplicate attribute '%s' in dimension "
                                    "'%s' level '%s' (also defined in level "
                                    "'%s')" % (attribute, self.name,
                                               level_name, first)))
                else:
                    attributes.add(attr_name)
                    first_occurence[attr_name] = level_name

                if not isinstance(attribute, Attribute):
                    results.append(('error',
                                    "Attribute '%s' in dimension '%s' is "
                                    "not instance of Attribute"
                                    % (attribute, self.name)))

                if attribute.dimension is not self:
                    results.append(('error',
                                    "Dimension (%s) of attribute '%s' does "
                                    "not match with owning dimension %s"
                                    % (attribute.dimension, attribute,
                                       self.name)))

        return results

    def __str__(self):
        return self.name

    def __repr__(self):
        return "<dimension: {name: '%s', levels: %s}>" % (self.name,
                                                          self._levels.keys())

    def localize(self, locale):
        localize_common(self, locale)

        attr_locales = locale.get("attributes", {})

        for attrib in self.all_attributes():
            if attrib.name in attr_locales:
                localize_common(attrib, attr_locales[attrib.name])

        level_locales = locale.get("levels") or {}
        for level in self.levels:
            level_locale = level_locales.get(level.name)
            if level_locale:
                level.localize(level_locale)

        hier_locales = locale.get("hierarcies")
        if hier_locales:
            for hier in self.hierarchies:
                hier_locale = hier_locales.get(hier.name)
                hier.localize(hier_locale)

    def localizable_dictionary(self):
        locale = {}
        locale.update(get_localizable_attributes(self))

        ldict = {}
        locale["levels"] = ldict

        for level in self.levels:
            ldict[level.name] = level.localizable_dictionary()

        hdict = {}
        locale["hierarchies"] = hdict

        for hier in self.hierarchies.values():
            hdict[hier.name] = hier.localizable_dictionary()

        return locale


class Hierarchy(object):
    """Dimension hierarchy - specifies order of dimension levels.

    Attributes:

    * `name`: hierarchy name
    * `dimension`: dimension the hierarchy belongs to
    * `label`: human readable name
    * `levels`: ordered list of levels or level names from `dimension`
    * `info` - custom information dictionary, might be used to store
      application/front-end specific information

    Some collection operations might be used, such as ``level in hierarchy``
    or ``hierarchy[index]``. String value ``str(hierarchy)`` gives the
    hierarchy name.

    """
    def __init__(self, name, levels, dimension=None, label=None, info=None):
        self.name = name
        self.label = label
        self.info = info or {}

        # if not dimension:
        #     raise ModelInconsistencyError("No dimension specified for "
        #                                   "hierarchy %s" % self.name)
        self._level_refs = levels
        self._levels = None

        if dimension:
            self.dimension = dimension
            self._set_levels(levels)

    def _set_levels(self, levels):
        if not levels:
            raise ModelInconsistencyError("Hierarchy level list should not be "
                                          "empty (in %s)" % self.name)

        self._levels = OrderedDict()
        for level in levels:
            level = self.dimension.level(level)
            self._levels[level.name] = level

    @property
    def levels(self):
        if not self._levels:
            self._set_levels(self._level_refs)

        return self._levels.values()

    @property
    def levels_dict(self):
        if not self._levels:
            self._set_levels(self._level_refs)

        return self._levels

    def __eq__(self, other):
        if not other or type(other) != type(self):
            return False
        elif self.name != other.name or self.label != other.label:
            return False
        elif self.levels != other.levels:
            return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return self.name

    def __len__(self):
        return len(self.levels)

    def __getitem__(self, item):
        return self.levels[item]

    def __contains__(self, item):
        if item in self.levels:
            return True
        return item in [level.name for level in self.levels]

    def levels_for_path(self, path, drilldown=False):
        """Returns levels for given path. If path is longer than hierarchy
        levels, `cubes.ArgumentError` exception is raised"""

        depth = 0 if not path else len(path)
        return self.levels_for_depth(depth, drilldown)

    def levels_for_depth(self, depth, drilldown=False):
        """Returns levels for given `depth`. If `path` is longer than
        hierarchy levels, `cubes.ArgumentError` exception is raised"""

        depth = depth or 0
        extend = 1 if drilldown else 0

        if depth + extend > len(self.levels):
            raise HierarchyError("Depth %d is longer than hierarchy "
                                 "levels %s (drilldown: %s)" %
                                 (depth, self._levels.keys(), drilldown))

        return self.levels[0:depth + extend]

    def next_level(self, level):
        """Returns next level in hierarchy after `level`. If `level` is last
        level, returns ``None``. If `level` is ``None``, then the first level
        is returned."""

        if not level:
            return self.levels[0]

        index = self.levels_dict.keys().index(str(level))
        if index + 1 >= len(self.levels):
            return None
        else:
            return self.levels[index + 1]

    def previous_level(self, level):
        """Returns previous level in hierarchy after `level`. If `level` is
        first level or ``None``, returns ``None``"""

        if level is None:
            return None

        index = self.levels_dict.keys().index(str(level))
        if index == 0:
            return None
        else:
            return self.levels[index - 1]

    def level_index(self, level):
        """Get order index of level. Can be used for ordering and comparing
        levels within hierarchy."""
        try:
            return self.levels_dict.keys().index(str(level))
        except ValueError:
            raise HierarchyError("Level %s is not part of hierarchy %s"
                                 % (str(level), self.name))

    def is_last(self, level):
        """Returns `True` if `level` is last level of the hierarchy."""

        return level == self.levels[-1]

    def rollup(self, path, level=None):
        """Rolls-up the path to the `level`. If `level` is ``None`` then path
        is rolled-up only one level.

        If `level` is deeper than last level of `path` the
        `cubes.HierarchyError` exception is raised. If `level` is the same as
        `path` level, nothing happens."""

        if level:
            last = self.level_index(level) + 1
            if last > len(path):
                raise HierarchyError("Can not roll-up: level '%s' in "
                                     "dimension '%s' is deeper than deepest "
                                     "element of path %s" %
                                     (str(level), self.dimension.name, path))
        else:
            if len(path) > 0:
                last = len(path) - 1
            else:
                last = None

        if last is None:
            return []
        else:
            return path[0:last]

    def path_is_base(self, path):
        """Returns True if path is base path for the hierarchy. Base path is a
        path where there are no more levels to be added - no drill down
        possible."""

        return path is not None and len(path) == len(self.levels)

    def key_attributes(self):
        """Return all dimension key attributes as a single list."""

        return [level.key for level in self.levels]

    def all_attributes(self):
        """Return all dimension attributes as a single list."""

        attributes = []
        for level in self.levels:
            attributes.extend(level.attributes)

        return attributes

    def to_dict(self, **options):
        """Convert to dictionary. Keys:

        * `name`: hierarchy name
        * `label`: human readable label (localizable)
        * `levels`: level names

        """

        out = IgnoringDictionary()
        out["name"] = self.name
        out["levels"] = [str(l) for l in self.levels]
        out["info"] = self.info

        if options.get("create_label"):
            out["label"] = self.label or to_label(self.name)
        else:
            out["label"] = self.label

        return out

    def localize(self, locale):
        localize_common(self, locale)

    def localizable_dictionary(self):
        locale = {}
        locale.update(get_localizable_attributes(self))

        return locale


class Level(object):
    """Object representing a hierarchy level. Holds all level attributes.

    This object is immutable, except localization. You have to set up all
    attributes in the initialisation process.

    Attributes:

    * `name`: level name
    * `dimension`: dimnesion the level is associated with
    * `attributes`: list of all level attributes. Raises `ModelError` when
      `attribute` list is empty.
    * `key`: name of level key attribute (for example: ``customer_number`` for
      customer level, ``region_code`` for region level, ``month`` for month
      level).  key will be used as a grouping field for aggregations. Key
      should be unique within level. If not specified, then the first
      attribute is used as key.
    * `order`: ordering of the level. `asc` for ascending, `desc` for
      descending or might be unspecified.
    * `order_attribute`: name of attribute that is going to be used for
      sorting, default is first attribute (usually key)
    * `label_attribute`: name of attribute containing label to be displayed
      (for example: ``customer_name`` for customer level, ``region_name`` for
      region level, ``month_name`` for month level)
    * `label`: human readable label of the level
    * `info`: custom information dictionary, might be used to store
      application/front-end specific information
    """

    def __init__(self, name, attributes, dimension=None, key=None,
                 order_attribute=None, order=None, label_attribute=None,
                 label=None, info=None):

        self.name = name
        self.dimension = dimension
        self.label = label
        self.info = info or {}

        if not attributes:
            raise ModelError("Attribute list should not be empty")

        self.attributes = attribute_list(attributes)

        # TODO: don't do this
        # NOTE: Affected by removal: mapper (mostly in SQL)
        for attribute in self.attributes:
            attribute.dimension = dimension

        if key:
            self.key = self.attribute(key)
        elif len(self.attributes) >= 1:
            self.key = self.attributes[0]
        else:
            raise ModelInconsistencyError("Attribute list should not be empty")

        # Set second attribute to be label attribute if label attribute is not
        # set. If dimension is flat (only one attribute), then use the only
        # key attribute as label.

        if label_attribute:
            self.label_attribute = self.attribute(label_attribute)
        else:
            if len(self.attributes) > 1:
                self.label_attribute = self.attributes[1]
            else:
                self.label_attribute = self.key

        # Set first attribute to be order attribute if order attribute is not
        # set

        if order_attribute:
            try:
                self.order_attribute = self.attribute(order_attribute)
            except NoSuchAttributeError:
                raise NoSuchAttributeError("Unknown order attribute %s in "
                                           "dimension %s, level %s" %
                                           (order_attribute,
                                            str(self.dimension), self.name))
        else:
            self.order_attribute = self.attributes[0]

        self.order = order

    def __eq__(self, other):
        if not other or type(other) != type(self):
            return False
        elif self.name != other.name \
                or self.label != other.label \
                or self.key != other.key:
            return False
        elif self.label_attribute != other.label_attribute:
            return False
        elif self.order_attribute != other.order_attribute:
            return False

        if self.attributes != other.attributes:
            return False

        # for attr in other.attributes:
        #     if attr not in self.attributes:
        #         return False

        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return self.name

    def __repr__(self):
        return str(self.to_dict())

    def __deepcopy__(self, memo):
        if self.order_attribute:
            order_attribute = str(self.order_attribute)
        else:
            order_attribute = None

        return Level(self.name,
                     attributes=copy.deepcopy(self.attributes, memo),
                     key=self.key.name,
                     order_attribute=order_attribute,
                     order=self.order,
                     label_attribute=self.label_attribute.name,
                     info=copy.copy(self.info),
                     label=copy.copy(self.label)
                     )

    def to_dict(self, full_attribute_names=False, **options):
        """Convert to dictionary"""

        out = IgnoringDictionary()
        out["name"] = self.name
        out["info"] = self.info

        if options.get("create_label"):
            out["label"] = self.label or to_label(self.name)
        else:
            out["label"] = self.label

        if full_attribute_names:
            out["key"] = self.key.ref()
            out["label_attribute"] = self.label_attribute.ref()
            out["order_attribute"] = self.order_attribute.ref()
        else:
            out["key"] = self.key.name
            out["label_attribute"] = self.label_attribute.name
            out["order_attribute"] = self.order_attribute.name

        out["order"] = self.order

        out["attributes"] = [attr.to_dict(**options) for attr in
                             self.attributes]
        return out

    def attribute(self, name):
        """Get attribute by `name`"""

        attrs = [attr for attr in self.attributes if attr.name == name]

        if attrs:
            return attrs[0]
        else:
            raise NoSuchAttributeError(name)

    @property
    def has_details(self):
        """Is ``True`` when level has more than one attribute, for all levels
        with only one attribute it is ``False``."""

        return len(self.attributes) > 1

    def localize(self, locale):
        localize_common(self, locale)

        if isinstance(locale, basestring):
            return

        attr_locales = locale.get("attributes")
        if attr_locales:
            logger = get_logger()
            logger.warn("'attributes' in localization dictionary of levels "
                        "is depreciated. Use list of `attributes` in "
                        "localization of dimension")

            for attrib in self.attributes:
                if attrib.name in attr_locales:
                    localize_common(attrib, attr_locales[attrib.name])

    def localizable_dictionary(self):
        locale = {}
        locale.update(get_localizable_attributes(self))

        adict = {}
        locale["attributes"] = adict

        for attribute in self.attributes:
            adict[attribute.name] = attribute.localizable_dictionary()

        return locale


class AttributeBase(object):
    ASC = 'asc'
    DESC = 'desc'

    def __init__(self, name, label=None, description=None, order=None,
                 info=None, format=None, **kwargs):
        """Base class for dimension attributes and measures.

        Attributes:

        * `name` - attribute name, used as identifier
        * `label` - attribute label displayed to a user
        * `order` - default order of this attribute. If not specified, then
          order is unexpected. Possible values are: ``'asc'`` or ``'desc'``.
          It is recommended and safe to use ``Attribute.ASC`` and
          ``Attribute.DESC``
        * `info` - custom information dictionary, might be used to store
          application/front-end specific information
        * `format` - application-specific display format information, useful
          for formatting numeric values of measure attributes

        String representation of the `AttributeBase` returns its `name`.

        `cubes.ArgumentError` is raised when unknown ordering type is
        specified.
        """
        self.name = name
        self.label = label
        self.description = description
        self.info = info or {}
        self.format = format
        # TODO: temporarily preserved, this should be present only in
        # Attribute object, not all kinds of attributes
        self.dimension = None

        if order:
            self.order = order.lower()
            if self.order.startswith("asc"):
                self.order = Attribute.ASC
            elif self.order.startswith("desc"):
                self.order = Attribute.DESC
            else:
                raise ArgumentError("Unknown ordering '%s' for attributes"
                                    " '%s'" % (order, self.ref()))
        else:
            self.order = None

    def __str__(self):
        return self.name

    def __repr__(self):
        return str(self.to_dict())

    def __eq__(self, other):
        if not isinstance(other, AttributeBase):
            return False

        # TODO: should we be this strict?
        return self.name == other.name \
            and self.label == other.label \
            and self.info == other.info \
            and self.description == other.description \
            and self.format == other.format

    def __ne__(self, other):
        return not self.__eq__(other)

    def to_dict(self, **options):
        # Use ordered dict for nicer JSON output
        d = IgnoringDictionary()
        d["name"] = self.name

        if options.get("create_label"):
            d["label"] = self.label or to_label(self.name)
        else:
            d["label"] = self.label

        d["description"] = self.description
        d["info"] = self.info
        d["format"] = self.format
        d["order"] = self.order

        d["full_name"] = self.ref()
        d["ref"] = self.ref()

        return d

    def localizable_dictionary(self):
        locale = {}
        locale.update(get_localizable_attributes(self))

        return locale

    def is_localizable(self):
        return False

    def ref(self, simplify=None, locale=None):
        return self.name


class Attribute(AttributeBase):

    def __init__(self, name, label=None, description=None, order=None,
                 info=None, format=None, dimension=None, locales=None,
                 **kwargs):
        """Dimension attribute.

        Attributes:

        * `name` - attribute name, used as identifier
        * `label` - attribute label displayed to a user
        * `locales` = list of locales that the attribute is localized to
        * `order` - default order of this attribute. If not specified, then
          order is unexpected. Possible values are: ``'asc'`` or ``'desc'``.
          It is recommended and safe to use ``Attribute.ASC`` and
          ``Attribute.DESC``
        * `info` - custom information dictionary, might be used to store
          application/front-end specific information
        * `format` - application-specific display format information, useful
          for formatting numeric values of measure attributes

        String representation of the `Attribute` returns its `name` (without
        dimension prefix).

        `cubes.ArgumentError` is raised when unknown ordering type is
        specified.
        """

        super(Attribute, self).__init__(name=name, label=label,
                                        description=description, order=order,
                                        info=info, format=format)

        self.dimension = dimension
        self.locales = locales or []

    def __deepcopy__(self, memo):
        return Attribute(self.name,
                         self.label,
                         dimension=self.dimension,
                         locales=copy.deepcopy(self.locales, memo),
                         order=copy.deepcopy(self.order, memo),
                         description=self.description,
                         info=copy.deepcopy(self.info, memo),
                         format=self.format)

    def __eq__(self, other):
        if not super(Attribute, self).__eq__(other):
            return False

        return str(self.dimension) == str(other.dimension) \
               and self.locales == other.locales

    def to_dict(self, **options):
        # FIXME: Depreciated key "full_name" in favour of "ref"
        d = super(Attribute, self).to_dict(**options)

        d["locales"] = self.locales

        return d

    def ref(self, simplify=True, locale=None):
        """Return full attribute reference. Append `locale` if it is one of
        attribute's locales, otherwise raise `cubes.ArgumentError`. If
        `simplify` is ``True``, then reference to an attribute of flat
        dimension without details will be just the dimension name.

        .. warning::

            This method might be renamed.

        """
        if locale:
            if not self.locales:
                raise ArgumentError("Attribute '%s' is not loalizable "
                                    "(localization %s requested)"
                                    % (self.name, locale))
            elif locale not in self.locales:
                raise ArgumentError("Attribute '%s' has no localization %s "
                                    "(has: %s)"
                                    % (self.name, locale, self.locales))
            else:
                locale_suffix = "." + locale
        else:
            locale_suffix = ""

        if self.dimension:
            if simplify and (self.dimension.is_flat
                             and not self.dimension.has_details):
                reference = self.dimension.name
            else:
                reference = self.dimension.name + '.' + str(self.name)
        else:
            reference = str(self.name)

        return reference + locale_suffix

    def is_localizable(self):
        return bool(self.locales)


def create_measure(md):
    """Create a measure object from metadata."""
    if isinstance(md, basestring):
        md = {"name": md}

    if not "name" in md:
        raise ModelError("Measure has no name.")

    return Measure(**md)


# TODO: give it a proper name
class Measure(AttributeBase):

    def __init__(self, name, label=None, description=None, order=None,
                 info=None, format=None, aggregates=None, formula=None,
                 expression=None, **kwargs):
        """Fact measure attribute.

        Properties:

        * `formula` – name of a formula for the measure
        * `aggregates` – list of default (relevant) aggregate functions that
          can be applied to this measure attribute.

        Note that if the `formula` is specified, it should not refer to any
        other measure that refers to this one (no circular reference).

        The `aggregates` is an optional property and is used for:
        * measure aggergate object preparation
        * optional validation

        String representation of a `Measure` returns its `name`.
        """
        super(Measure, self).__init__(name=name, label=label,
                                      description=description, order=order,
                                      info=info, format=format)

        self.expression = expression
        self.formula = formula
        self.aggregates = aggregates

    def __deepcopy__(self, memo):
        return Measure(self.name, self.label,
                       order=copy.deepcopy(self.order, memo),
                       description=self.description,
                       info=copy.deepcopy(self.info, memo),
                       format=self.format,
                       aggregates=self.aggregates,
                       expression=self.expression,
                       formula=self.formula)

    def __eq__(self, other):
        if not super(Measure, self).__eq__(other):
            return False

        return self.aggregates == other.aggregates \
               and self.formula == other.formula

    def to_dict(self, **options):
        d = super(Measure, self).to_dict(**options)
        d["formula"] = self.formula
        d["aggregates"] = self.aggregates
        d["expression"] = self.expression

        return d

    def default_aggregates(self):
        """Creates default measure aggregates from a list of receiver's
        aggregates. This is just a convenience function, correct models should
        contain explicit list of aggregates. If no aggregates are specified,
        then the only aggregate `sum` is assumed."""

        aggregates = []

        for agg in (self.aggregates or ["sum"]):
            name = "%s_%s" % (self.name, agg)
            if self.label:
                label = "%s – %s" % (self.label, agg)
            else:
                label = None

            aggregate = MeasureAggregate(name=name,
                                         label=label,
                                         description=self.description,
                                         order=self.order,
                                         info=self.info,
                                         format=self.format,
                                         measure=self.name,
                                         function=agg)
            aggregates.append(aggregate)

        return aggregates


def create_measure_aggregate(md):
    if isinstance(md, basestring):
        md = {"name": md}

    if not "name" in md:
        raise ModelError("Measure aggregate has no name.")

    return MeasureAggregate(**md)


# TODO: alternative names: MeasureAggregate, AggregatedMeasure, Aggregate
class MeasureAggregate(AttributeBase):

    def __init__(self, name, label=None, description=None, order=None,
                 info=None, format=None, measure=None, function=None,
                 formula=None, expression=None, **kwargs):
        """Masure aggregate

        Attributes:

        * `function` – aggregation function for the measure
        * `formula` – name of a formula that contains the arithemtic
          expression (optional)
        * `measure` – measure for this aggregate (optional)
        * `expression` – arithmetic expression
        """

        super(MeasureAggregate, self).__init__(name=name, label=label,
                                               description=description,
                                               order=order, info=info,
                                               format=format)

        self.function = function
        self.formula = formula
        self.expression = expression
        self.measure = measure

    def __deepcopy__(self, memo):
        return MeasureAggregate(self.name,
                                self.label,
                                order=copy.deepcopy(self.order, memo),
                                description=self.description,
                                info=copy.deepcopy(self.info, memo),
                                format=self.format,
                                measure=self.measure,
                                function=self.function,
                                formula=self.formula,
                                expression=self.expression)

    def __eq__(self, other):
        if not super(Attribute, self).__eq__(other):
            return False

        return str(self.function) == str(other.function) \
            and self.measure == other.measure \
            and self.formula == other.formula \
            and self.expression == other.expression

    def to_dict(self, **options):
        d = super(Attribute, self).to_dict(**options)
        d["function"] = self.aggregation
        d["formula"] = self.formula
        d["expression"] = self.expression
        d["measure"] = self.formula

        return d


def create_attribute(obj, class_=None):
    """Makes sure that the `obj` is an ``Attribute`` instance. If `obj` is a
    string, then new instance is returned. If it is a dictionary, then the
    dictionary values are used for ``Attribute``instance initialization."""

    class_ = class_ or Attribute

    if isinstance(obj, basestring):
        return class_(obj)
    elif isinstance(obj, dict):
        return class_(**obj)
    else:
        return obj


def attribute_list(attributes, class_=None):
    """Create a list of attributes from a list of strings or dictionaries.
    see :func:`cubes.coalesce_attribute` for more information."""

    if not attributes:
        return []

    result = [create_attribute(attr, class_) for attr in attributes]

    return result


def measure_list(measures):
    if not measures:
        return []

    result = []
    for attr in measures:
        if isinstance(attr, basestring):
            measure = Measure(name=attr)
        elif isinstance(attr, dict):

            if "aggregations" in attr:
                logger = get_logger()
                logger.warn("'aggregations' is depreciated, use 'aggregates'")
                attr = dict(attr)
                attr["aggergates"] = attr.pop("aggregations")

            measure = Measure(**attr)

        elif isinstance(attr, Measure):
            measure = measure
        else:
            raise ModelError("Unknown object type %s for a measure" %
                             type(attr))
        result.append(measure)

    return result


def localize_common(obj, trans):
    """Localize common attributes: label and description. `trans` should be a
    dictionary or a string. If it is just a string, then only `label` will be
    localized."""
    if isinstance(trans, basestring):
        obj.label = trans
    else:
        if "label" in trans:
            obj.label = trans["label"]
        if "description" in trans:
            obj.description = trans["description"]


def localize_attributes(attribs, translations):
    """Localize list of attributes. `translations` should be a dictionary with
    keys as attribute names, values are dictionaries with localizable
    attribute metadata, such as ``label`` or ``description``."""
    for (name, atrans) in translations.items():
        attrib = attribs[name]
        localize_common(attrib, atrans)


def get_localizable_attributes(obj):
    """Returns a dictionary with localizable attributes of `obj`."""

    # FIXME: use some kind of class attribute to get list of localizable
    # attributes

    locale = {}
    if hasattr(obj, "label"):
        locale["label"] = obj.label

    if hasattr(obj, "description"):
        locale["description"] = obj.description

    return locale


def aggregate_ref(measure, aggregate):
    """Creates a reference string for measure aggregate. Current
    implementation joins the measure name and aggregate name with an
    underscore character `'_'`. Use this method in in a backend to create
    valid aggregate reference. See also `split_aggregate_ref()`"""

    return "%s_%s" % (measure, aggregate)


def split_aggregate_ref(measure):
    """Splits aggregate measure reference into measure name and aggregate
    name. Use this method in presenters to correctly get measure name and
    aggregate name from aggregate reference that was created by
    `aggregate_ref()` function.
    """

    measure = str(measure)

    r = measure.rfind("_")

    if r == -1 or r >= len(measure) - 1:
        if r == -1:
            meaning = measure + "_sum"
        else:
            meaning = measure + "sum"

        raise ArgumentError("Invalid aggregate reference '%s'. "
                            "Did you mean '%s'?" % (measure, meaning))

    return (measure[:r], measure[r + 1:])
