#!/usr/bin/env python3
#
#  IRIS Source Code
#  Copyright (C) 2021 - Airbus CyberSecurity (SAS)
#  ir@cyberactionlab.net
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

# IMPORTS ------------------------------------------------
import marshmallow
from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import request
from flask import session
from flask import url_for
from flask_login import current_user

from app import db
from app.blueprints.profile.profile_routes import profile_blueprint
from app.datamgmt.case.case_db import get_case
from app.datamgmt.manage.manage_cases_db import list_cases_dict
from app.datamgmt.manage.manage_groups_db import get_groups_list
from app.datamgmt.manage.manage_organisations_db import get_organisations_list
from app.datamgmt.manage.manage_srv_settings_db import get_srv_settings
from app.datamgmt.manage.manage_users_db import add_case_access_to_user
from app.datamgmt.manage.manage_users_db import create_user
from app.datamgmt.manage.manage_users_db import delete_user
from app.datamgmt.manage.manage_users_db import get_user
from app.datamgmt.manage.manage_users_db import get_user_by_username
from app.datamgmt.manage.manage_users_db import get_user_details
from app.datamgmt.manage.manage_users_db import get_user_effective_permissions
from app.datamgmt.manage.manage_users_db import get_user_organisations
from app.datamgmt.manage.manage_users_db import get_users_id_view_from_user_id
from app.datamgmt.manage.manage_users_db import get_users_list
from app.datamgmt.manage.manage_users_db import get_users_list_restricted
from app.datamgmt.manage.manage_users_db import get_users_list_restricted_user_view
from app.datamgmt.manage.manage_users_db import get_users_list_user_view
from app.datamgmt.manage.manage_users_db import remove_case_access_from_user
from app.datamgmt.manage.manage_users_db import update_user
from app.datamgmt.manage.manage_users_db import update_user_groups
from app.datamgmt.manage.manage_users_db import update_user_orgs
from app.forms import AddUserForm
from app.iris_engine.access_control.utils import ac_flag_match_mask
from app.iris_engine.access_control.utils import ac_get_all_access_level
from app.iris_engine.access_control.utils import ac_recompute_effective_ac
from app.iris_engine.utils.tracker import track_activity
from app.models.authorization import Permissions
from app.schema.marshables import UserSchema
from app.util import ac_api_requires
from app.util import ac_api_return_access_denied
from app.util import ac_requires
from app.util import ac_return_access_denied
from app.util import api_login_required
from app.util import is_authentication_local
from app.util import response_error
from app.util import response_success

manage_users_blueprint = Blueprint(
    'manage_users',
    __name__,
    template_folder='templates'
)


@manage_users_blueprint.route('/manage/users/list', methods=['GET'])
@ac_api_requires(Permissions.read_users, Permissions.manage_users)
def manage_users_list(caseid):

    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        users = get_users_list_user_view(user_id=current_user.id)
    else:
        users = get_users_list()

    return response_success('', data=users)


@manage_users_blueprint.route('/manage/users/add/modal', methods=['GET'])
@ac_requires(Permissions.manage_users)
def add_user_modal(caseid, url_redir):
    if url_redir:
        return redirect(url_for('manage_users.add_user', cid=caseid))

    user = None
    form = AddUserForm()
    if ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        orgs_choices = [(org.org_id, org.org_name) for org in get_organisations_list()]
    else:
        orgs_choices = [(org['org_id'], org['org_name']) for org in get_user_organisations(current_user.id)]

    form.user_primary_organisation_id.choices = orgs_choices
    server_settings = get_srv_settings()

    return render_template("modal_add_user.html", form=form, user=user, server_settings=server_settings)


@manage_users_blueprint.route('/manage/users/add', methods=['POST'])
@ac_api_requires(Permissions.manage_users)
def add_user(caseid):
    try:

        # validate before saving
        user_schema = UserSchema()
        jsdata = request.get_json()
        jsdata['user_id'] = 0
        jsdata['active'] = jsdata.get('active', True)
        cuser = user_schema.load(jsdata, partial=True)
        user = create_user(user_name=cuser.name,
                           user_login=cuser.user,
                           user_email=cuser.email,
                           user_password=cuser.password,
                           primary_org=jsdata.get('user_primary_organisation_id'),
                           user_active=jsdata.get('active'))

        if cuser:
            track_activity("created user {}".format(user.user), caseid=caseid)
            return response_success("user created", data=user_schema.dump(user))

        return response_error("Unable to create user for internal reasons")

    except marshmallow.exceptions.ValidationError as e:
        return response_error(msg="Data error", data=e.messages, status=400)


@manage_users_blueprint.route('/manage/users/<int:cur_id>', methods=['GET'])
@ac_api_requires(Permissions.read_users, Permissions.manage_users)
def view_user(cur_id, caseid):

    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if cur_id not in get_users_id_view_from_user_id(current_user.id):
            return ac_api_return_access_denied(caseid)

    user = get_user_details(user_id=cur_id)

    if not user:
        return response_error("Invalid user ID")

    return response_success(data=user)


@manage_users_blueprint.route('/manage/users/<int:cur_id>/modal', methods=['GET'])
@ac_requires(Permissions.read_users, Permissions.manage_users)
def view_user_modal(cur_id, caseid, url_redir):
    if url_redir:
        return redirect(url_for('manage_users.add_user', cid=caseid))

    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if cur_id not in get_users_id_view_from_user_id(current_user.id):
            print(get_users_id_view_from_user_id(current_user.id))
            return ac_return_access_denied(caseid)

    form = AddUserForm()
    user = get_user_details(cur_id)

    if not user:
        return response_error("Invalid user ID")

    permissions = get_user_effective_permissions(cur_id)

    form.user_login.render_kw = {'value': user.get('user_login')}
    form.user_name.render_kw = {'value': user.get('user_name')}
    form.user_email.render_kw = {'value': user.get('user_email')}

    if ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        orgs_choices = [(org.org_id, org.org_name) for org in get_organisations_list()]
    else:
        orgs_choices = [(org['org_id'], org['org_name']) for org in get_user_organisations(current_user.id)]
    form.user_primary_organisation_id.choices = orgs_choices
    form.user_primary_organisation_id(disabled=True)
    form.user_primary_organisation_id.render_kw = {'value': user.get('user_primary_organisation_id')}

    server_settings = get_srv_settings()

    return render_template("modal_add_user.html", form=form, user=user, server_settings=server_settings,
                           permissions=permissions)


@manage_users_blueprint.route('/manage/users/<int:cur_id>/groups/modal', methods=['GET'])
@ac_requires(Permissions.manage_users)
def manage_user_group_modal(cur_id, caseid, url_redir):
    if url_redir:
        return redirect(url_for('manage_users.add_user', cid=caseid))

    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if cur_id not in get_users_id_view_from_user_id(current_user.id):
            return ac_return_access_denied(caseid)

    user = get_user_details(cur_id)
    if not user:
        return response_error("Invalid user ID")

    groups = get_groups_list()

    return render_template("modal_manage_user_groups.html", groups=groups, user=user)


@manage_users_blueprint.route('/manage/users/<int:cur_id>/groups/update', methods=['POST'])
@ac_api_requires(Permissions.manage_users)
def manage_user_group_(cur_id, caseid):
    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if cur_id not in get_users_id_view_from_user_id(current_user.id):
            return ac_api_return_access_denied(caseid)

    if not request.is_json:
        return response_error("Invalid request", status=400)

    if not request.json.get('groups_membership'):
        return response_error("Invalid request", status=400)

    if type(request.json.get('groups_membership')) is not list:
        return response_error("Expected list of groups ID", status=400)

    user = get_user(cur_id)
    if not user:
        return response_error("Invalid user ID")

    update_user_groups(user_id=cur_id,
                       groups=request.json.get('groups_membership'))

    return response_success("User groups updated", data=user)


@manage_users_blueprint.route('/manage/users/<int:cur_id>/organisations/modal', methods=['GET'])
@ac_requires(Permissions.manage_users)
def manage_user_orgs_modal(cur_id, caseid, url_redir):
    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if cur_id not in get_users_id_view_from_user_id(current_user.id):
            return ac_return_access_denied(caseid)

    if url_redir:
        return redirect(url_for('manage_users.add_user', cid=caseid))

    user = get_user_details(cur_id)
    if not user:
        return response_error("Invalid user ID")

    orgs = get_organisations_list()

    return render_template("modal_manage_user_orgs.html", orgs=orgs, user=user)


@manage_users_blueprint.route('/manage/users/<int:cur_id>/organisations/update', methods=['POST'])
@ac_api_requires(Permissions.manage_users)
def manage_user_orgs(cur_id, caseid):
    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if cur_id not in get_users_id_view_from_user_id(current_user.id):
            return ac_api_return_access_denied(caseid)

    if not request.is_json:
        return response_error("Invalid request", status=400)

    if not request.json.get('orgs_membership'):
        return response_error("Invalid request", status=400)

    if type(request.json.get('orgs_membership')) is not list:
        return response_error("Expected list of organisations ID", status=400)

    user = get_user(cur_id)
    if not user:
        return response_error("Invalid user ID")

    success, logs = update_user_orgs(user_id=cur_id,
                                     orgs=request.json.get('orgs_membership'))
    if not success:
        return response_error(logs)

    return response_success(logs, data=user)


@manage_users_blueprint.route('/manage/users/<int:cur_id>/cases-access/modal', methods=['GET'])
@ac_requires(Permissions.manage_users)
def manage_user_cac_modal(cur_id, caseid, url_redir):
    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if cur_id not in get_users_id_view_from_user_id(current_user.id):
            return ac_return_access_denied(caseid)

    if url_redir:
        return redirect(url_for('manage_users.add_user', cid=caseid))

    user = get_user_details(cur_id)
    if not user:
        return response_error("Invalid user ID")

    cases_list = list_cases_dict(current_user.id)

    user_cases_access = [case.get('case_id') for case in user.get('user_cases_access')]
    outer_cases_list = []
    for case in cases_list:
        if case.get('case_id') not in user_cases_access:
            outer_cases_list.append({
                "case_id": case.get('case_id'),
                "case_name": case.get('case_name')
            })

    access_levels = ac_get_all_access_level()

    return render_template("modal_add_user_cac.html", user=user, outer_cases=outer_cases_list,
                           access_levels=access_levels)


@manage_users_blueprint.route('/manage/users/<int:cur_id>/cases-access/add', methods=['POST'])
@ac_api_requires(Permissions.manage_users)
def manage_user_cac_add_case(cur_id, caseid):
    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if cur_id not in get_users_id_view_from_user_id(current_user.id):
            return ac_api_return_access_denied(caseid)

    if not request.is_json:
        return response_error("Invalid request, expecting JSON")

    data = request.get_json()
    if not data:
        return response_error("Invalid request, expecting JSON")

    user = get_user(cur_id)
    if not user:
        return response_error("Invalid user ID")

    if not isinstance(data.get('access_level'), int):
        try:
            data['access_level'] = int(data.get('access_level'))
        except:
            return response_error("Expecting access_level as int")

    if not isinstance(data.get('cases_list'), list):
        return response_error("Expecting cases_list as list")

    user, logs = add_case_access_to_user(user, data.get('cases_list'), data.get('access_level'))
    if not user:
        return response_error(msg=logs)

    group = get_user_details(cur_id)

    return response_success(data=group)


@manage_users_blueprint.route('/manage/users/<int:cur_id>/cases-access/delete/<int:cur_id_2>', methods=['GET'])
@ac_api_requires(Permissions.manage_groups)
def manage_user_cac_delete_case(cur_id, cur_id_2, caseid):
    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if cur_id not in get_users_id_view_from_user_id(current_user.id):
            return ac_api_return_access_denied(caseid)

    user = get_user(cur_id)
    if not user:
        return response_error("Invalid user ID")

    case = get_case(cur_id_2)
    if not case:
        return response_error("Invalid user ID")

    remove_case_access_from_user(user.id, case.case_id)
    user = get_user_details(cur_id)

    return response_success('Case access removed from user', data=user)


@manage_users_blueprint.route('/manage/users/update/<int:cur_id>', methods=['POST'])
@ac_api_requires(Permissions.manage_users)
def update_user_api(cur_id, caseid):
    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if cur_id not in get_users_id_view_from_user_id(current_user.id):
            return ac_api_return_access_denied(caseid)

    try:
        user = get_user(cur_id)
        if not user:
            return response_error("Invalid user ID for this case")

        # validate before saving
        user_schema = UserSchema()
        jsdata = request.get_json()
        jsdata['user_id'] = cur_id
        cuser = user_schema.load(jsdata, instance=user, partial=True)
        update_user(password=jsdata.get('user_password'),
                    primary_org=jsdata.get('user_primary_organisation_id'),
                    user=user)
        db.session.commit()

        if cuser:
            track_activity("updated user {}".format(user.user), caseid=caseid)
            return response_success("User updated", data=user_schema.dump(user))

        return response_error("Unable to update user for internal reasons")

    except marshmallow.exceptions.ValidationError as e:
        return response_error(msg="Data error", data=e.messages, status=400)


@manage_users_blueprint.route('/manage/users/deactivate/<int:cur_id>', methods=['GET'])
@ac_api_requires(Permissions.manage_users)
def deactivate_user_api(cur_id, caseid):
    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if cur_id not in get_users_id_view_from_user_id(current_user.id):
            return ac_api_return_access_denied(caseid)

    user = get_user(cur_id)
    if not user:
        return response_error("Invalid user ID for this case")

    user.active = False
    db.session.commit()
    user_schema = UserSchema()

    track_activity("user {} deactivated".format(user.user), caseid=caseid)
    return response_success("User deactivated", data=user_schema.dump(user))


@manage_users_blueprint.route('/manage/users/activate/<int:cur_id>', methods=['GET'])
@ac_api_requires(Permissions.manage_users)
def activate_user_api(cur_id, caseid):
    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if cur_id not in get_users_id_view_from_user_id(current_user.id):
            return ac_api_return_access_denied(caseid)

    user = get_user(cur_id)
    if not user:
        return response_error("Invalid user ID for this case")

    user.active = True
    db.session.commit()
    user_schema = UserSchema()

    track_activity("user {} activated".format(user.user), caseid=caseid)
    return response_success("User activated", data=user_schema.dump(user))


if is_authentication_local():
    @manage_users_blueprint.route('/manage/users/delete/<int:cur_id>', methods=['GET'])
    @ac_api_requires(Permissions.manage_users)
    def view_delete_user(cur_id, caseid):
        if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
            if cur_id not in get_users_id_view_from_user_id(current_user.id):
                return ac_api_return_access_denied(caseid)

        try:
            user = get_user(cur_id)
            if not user:
                return response_error("Invalid user ID")

            if user.active is True:
                response_error("Cannot delete active user")
                track_activity(message="tried to delete active user ID {}".format(cur_id), caseid=caseid)
                return response_error("Cannot delete active user")

            delete_user(user.id)

            track_activity(message="deleted user ID {}".format(cur_id), caseid=caseid)
            return response_success("Deleted user ID {}".format(cur_id))

        except Exception as e:
            db.session.rollback()
            track_activity(message="tried to delete active user ID {}".format(cur_id), caseid=caseid)
            return response_error("Cannot delete active user")


# Unrestricted section - non admin available
@manage_users_blueprint.route('/manage/users/lookup/id/<int:cur_id>', methods=['GET'])
@ac_api_requires()
def exists_user_restricted(cur_id, caseid):
    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if cur_id not in get_users_id_view_from_user_id(current_user.id):
            return ac_api_return_access_denied(caseid)

    user = get_user(cur_id)
    if not user:
        return response_error("Invalid user ID")

    output = {
        "user_login": user.user,
        "user_id": user.id,
        "user_name": user.name
    }

    return response_success(data=output)


@manage_users_blueprint.route('/manage/users/lookup/login/<string:login>', methods=['GET'])
@ac_api_requires()
def lookup_name_restricted(login, caseid):
    user = get_user_by_username(login)
    if not user:
        return response_error("Invalid login")

    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        if user.id not in get_users_id_view_from_user_id(current_user.id):
            return ac_api_return_access_denied(caseid)

    output = {
        "user_login": user.user,
        "user_id": user.id,
        "user_uuid": user.uuid,
        "user_name": user.name,
        "user_email": user.email,
        "user_active": user.active
    }

    return response_success(data=output)


@manage_users_blueprint.route('/manage/users/restricted/list', methods=['GET'])
@ac_api_requires()
def manage_users_list_restricted(caseid):

    if not ac_flag_match_mask(session['permissions'], Permissions.manage_organisations.value):
        users = get_users_list_restricted_user_view(user_id=current_user.id)
    else:
        users = get_users_list_restricted()

    return response_success('', data=users)
